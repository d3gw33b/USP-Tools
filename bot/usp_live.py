#!/usr/bin/env python3
"""Keeps the USP bot online: answers !usp commands and counts votes the moment they happen.

Run it on any computer that stays on:  python usp_live.py
To check it connects and then stop:    python usp_live.py --for 90
To stop a copy that's running:          python usp_live.py --stop
It reads DISCORD_BOT_TOKEN, DISCORD_OWNER_IDS and DISCORD_CHANNEL_IDS from the environment, or from a
file called bot.env next to this one (one KEY=value per line). Never commit bot.env.

While it runs, the 15-minute GitHub check stands back. When it stops, the GitHub check takes over again.
Standard library only.
"""
import base64, json, os, queue, random, socket, ssl, struct, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usp_bot as B

GATEWAY = "gateway.discord.gg"
INTENTS = 1 | 512 | 1024 | 32768  # guilds, server messages, server message reactions, message content
FATAL = {4004: "the bot token is wrong (reset it and update bot.env)",
         4013: "the gateway intents are invalid",
         4014: "Message Content Intent is off (turn it on in the developer portal, Bot page)"}
CHECK_EVERY = 60  # seconds between timer checks; also how often it tells the GitHub check it's alive


class Closed(Exception):
    def __init__(self, code):
        super().__init__(f"closed with code {code}")
        self.code = code


class WebSocket:
    """Just enough of a websocket client for Discord's gateway."""

    def __init__(self, host, path):
        raw = socket.create_connection((host, 443), timeout=30)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: {B.UA}\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            self._fill()
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("gateway refused the connection")
        self.sock.settimeout(None)
        self.lock = threading.Lock()

    def _fill(self):
        chunk = self.sock.recv(65536)
        if not chunk:
            raise Closed(1006)
        self.buf += chunk

    def _take(self, n):
        while len(self.buf) < n:
            self._fill()
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        parts, kind = [], None
        while True:
            b1, b2 = self._take(2)
            op, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._take(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._take(8))[0]
            mask = self._take(4) if b2 & 0x80 else None
            data = self._take(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 8:
                raise Closed(struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 1005)
            if op == 9:
                self._send(10, data)
                continue
            if op == 10:
                continue
            if op in (1, 2):
                kind, parts = op, [data]
            elif op == 0:
                parts.append(data)
            if b1 & 0x80 and kind:
                return b"".join(parts).decode()

    def _send(self, op, data):
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | op])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        with self.lock:
            self.sock.sendall(head + mask + body)

    def send(self, obj):
        self._send(1, json.dumps(obj).encode())

    def close(self):
        try:
            self._send(8, struct.pack(">H", 1000))
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def gateway(token, events, online):
    """One connection. Puts (event name, data) on the queue until the connection ends."""
    ws = WebSocket(GATEWAY, "/?v=10&encoding=json")
    stop = threading.Event()
    try:
        hello = json.loads(ws.recv())
        every = hello["d"]["heartbeat_interval"] / 1000
        seq, acked = [None], [True]

        def beat():
            stop.wait(every * random.random())
            while not stop.is_set():
                if not acked[0]:  # Discord stopped answering: drop the connection and reconnect
                    ws.close()
                    return
                acked[0] = False
                try:
                    ws.send({"op": 1, "d": seq[0]})
                except Exception:
                    return
                stop.wait(every)

        threading.Thread(target=beat, daemon=True).start()
        ws.send({"op": 2, "d": {"token": token, "intents": INTENTS,
                                "properties": {"os": sys.platform, "browser": "usp-bot", "device": "usp-bot"},
                                "presence": {"status": "online", "afk": False, "since": None,
                                             "activities": [{"name": "USP votes", "type": 3}]}}})
        while True:
            p = json.loads(ws.recv())
            if p.get("s") is not None:
                seq[0] = p["s"]
            if p["op"] == 11:
                acked[0] = True
            elif p["op"] == 1:
                ws.send({"op": 1, "d": seq[0]})
            elif p["op"] in (7, 9):  # Discord asked for a fresh connection
                return
            elif p["op"] == 0:
                if p["t"] == "READY":
                    online.set()
                    print("Connected: the bot shows as online.")
                events.put((p["t"], p["d"]))
    finally:
        online.clear()
        stop.set()
        ws.close()


class Live:
    def __init__(self, cfg):
        self.cfg = cfg
        self.settings, self.sid, self.me = B.load_settings(cfg)
        self.chans = set(cfg["ch"].values())
        self.seen = set()
        self.online = threading.Event()
        self.synced = False  # caught up on commands sent while it was offline

    def save(self):
        B.save_settings(self.cfg, self.settings, self.sid)

    def catch_up(self):
        B.ensure_help(self.cfg, self.me)
        cards = B.find_cards(self.cfg, self.me)
        n = B.read_commands(self.cfg, self.settings, cards, B.now_ms(), self.seen)
        B.check_cards(self.cfg, self.settings, cards)
        self.synced = True
        self.settings["live"] = True
        self.save()
        print(f"Caught up ({n} command(s) sent while offline).")

    def on_message(self, d):
        if d.get("channel_id") not in self.chans or d["id"] in self.seen:
            return
        self.seen.add(d["id"])
        before = json.dumps(self.settings, sort_keys=True)
        if B.run_command(self.cfg, self.settings, B.find_cards(self.cfg, self.me), d):
            print("Answered a command.")
            if json.dumps(self.settings, sort_keys=True) != before:
                self.save()

    def on_reaction(self, d):
        if d.get("channel_id") != self.cfg["ch"]["voting"] or d.get("user_id") == self.me:
            return
        m = B.dc("GET", f"/channels/{d['channel_id']}/messages/{d['message_id']}")
        if m["author"]["id"] != self.me or not m.get("embeds"):
            return
        st = B.parse_card(m["embeds"][0])
        if st and st["state"] == "open" and B.check_card(self.cfg, self.settings, m, st, B.now_ms() // 1000):
            print("A vote was decided.")

    def check_in(self):
        """Timer check, and moves the cursor so the GitHub check knows this bot is alive."""
        B.check_cards(self.cfg, self.settings, B.find_cards(self.cfg, self.me))
        if self.online.is_set() and self.synced:
            self.settings["cursor"] = max(self.settings["cursor"], B.now_ms() - 10_000)
            self.settings["live"] = True
            self.save()
        if len(self.seen) > 5000:
            self.seen = set(sorted(self.seen, key=int)[-1000:])

    def work(self, events):
        last = 0
        while True:
            try:
                name, d = events.get(timeout=5)
            except queue.Empty:
                name, d = None, None
            try:
                if name == "READY":
                    self.synced = False
                    self.catch_up()
                elif name == "MESSAGE_CREATE" and self.synced:
                    self.on_message(d)
                elif name in ("MESSAGE_REACTION_ADD", "MESSAGE_REACTION_REMOVE") and self.synced:
                    self.on_reaction(d)
                if time.time() - last >= CHECK_EVERY:
                    last = time.time()
                    self.check_in()
            except Exception as e:
                print(f"Something failed ({type(e).__name__}: {e}); carrying on.")


HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_PORT = 47613  # a local port held while the bot runs, so only one copy runs and --stop can reach it


def load_env_file():
    path = os.path.join(HERE, "bot.env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def hold_lock(stop):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return None
    s.listen(1)

    def serve():
        while not stop.is_set():
            c, _ = s.accept()
            with c:
                if c.recv(16) == b"stop":
                    stop.set()

    threading.Thread(target=serve, daemon=True).start()
    return s


def connect_loop(live, events, stop):
    wait = 1
    while not stop.is_set():
        started = time.time()
        try:
            gateway(os.environ["DISCORD_BOT_TOKEN"], events, live.online)
            print("Reconnecting...")
        except Closed as e:
            if e.code in FATAL:
                print(f"Stopped: {FATAL[e.code]}.")
                stop.set()
                return
            print(f"Connection dropped ({e.code}); reconnecting.")
        except (OSError, ConnectionError, ValueError) as e:
            print(f"Connection problem ({type(e).__name__}); retrying.")
        wait = 1 if time.time() - started > 60 else min(wait * 2, 60)
        stop.wait(wait)


def main():
    if sys.stdout is None:  # started hidden (pythonw): write a log next to this file instead
        sys.stdout = sys.stderr = open(os.path.join(HERE, "bot.log"), "a", encoding="utf-8", buffering=1)
    if "--stop" in sys.argv:
        try:
            socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=3).sendall(b"stop")
            print("Told the running bot to stop.")
        except OSError:
            print("The bot isn't running.")
        return
    load_env_file()
    cfg = B.env_config()
    if not cfg:
        print("Missing DISCORD_BOT_TOKEN, DISCORD_OWNER_IDS or DISCORD_CHANNEL_IDS (put them in bot.env).")
        sys.exit(1)
    stop = threading.Event()
    lock = hold_lock(stop)
    if lock is None:
        print("The bot is already running on this computer.")
        return
    print(time.strftime("%Y-%m-%d %H:%M ") + "Starting the bot.")
    if "--for" in sys.argv:  # run for a while, then stop cleanly (used by the bot-live-check workflow)
        threading.Timer(float(sys.argv[sys.argv.index("--for") + 1]), stop.set).start()
    live = Live(cfg)
    events = queue.Queue()
    threading.Thread(target=live.work, args=(events,), daemon=True).start()
    threading.Thread(target=connect_loop, args=(live, events, stop), daemon=True).start()
    try:
        while not stop.wait(1):
            pass
    except KeyboardInterrupt:
        pass
    live.settings["live"] = False  # hand back to the GitHub check straight away
    if live.synced:
        live.settings["cursor"] = max(live.settings["cursor"], B.now_ms() - 2000)
    try:
        live.save()
    except Exception:
        pass
    print("Bot stopped.")


if __name__ == "__main__":
    main()
