# Minimal reader for HGPAK archives (5.50+). Windows chunks are zstd, 0x10000 bytes decompressed each.
# Layout: "HGPAK" + 3 pad, then <QQQ?7xQ> version, file_count, chunk_count, compressed, data_offset;
# file_count x (16-byte md5 of path, u64 offset, u64 size); chunk_count x u64 compressed size (each padded to 0x10);
# file 0 is the manifest (CRLF-separated paths of files 1..n).
# usage: hgpak.py list PAK | hgpak.py extract PAK OUTDIR [glob...]
import sys, struct, os, fnmatch, zstandard
CH = 0x10000
class Pak:
    def __init__(self, path):
        self.f = open(path, 'rb'); f = self.f
        assert f.read(5) == b'HGPAK'; f.read(3)
        self.version, self.nfiles, self.nchunks, self.compressed, self.data_off = struct.unpack('<QQQ?7xQ', f.read(0x28))
        self.index = [struct.unpack('<16sQQ', f.read(0x20)) for _ in range(self.nfiles)]
        self.sizes = struct.unpack(f'<{self.nchunks}Q', f.read(8 * self.nchunks)) if self.compressed else ()
        self.offs = []; p = self.data_off
        for s in self.sizes: self.offs.append(p); p += (s + 15) & ~15
        self.z = zstandard.ZstdDecompressor(); self.cache = {}
        man = self.read_range(*self._span(0)).rstrip(b'\r\n').split(b'\r\n')
        self.files = {}
        for i, n in enumerate(man):
            if n: self.files[n.decode()] = self._span(i + 1)
    def _span(self, i):
        _, off, size = self.index[i]
        return (off - self.data_off if self.compressed else off), size
    def chunk(self, i):
        if i not in self.cache:
            self.f.seek(self.offs[i]); raw = self.f.read(self.sizes[i])
            try: d = self.z.decompress(raw, max_output_size=CH)
            except zstandard.ZstdError: d = raw  # stored uncompressed
            if len(self.cache) > 64: self.cache.clear()
            self.cache[i] = d
        return self.cache[i]
    def read_range(self, off, size):
        if not self.compressed: self.f.seek(off); return self.f.read(size)
        out = bytearray(); pos = off
        while pos < off + size:
            c = self.chunk(pos // CH); s = pos % CH; e = min(CH, s + (off + size - pos))
            out += c[s:e]; pos += e - s
        return bytes(out)
    def read(self, name): return self.read_range(*self.files[name])
if __name__ == '__main__':
    cmd, pak = sys.argv[1:3]; P = Pak(pak)
    if cmd == 'list':
        for n, (o, s) in P.files.items(): print(s, n)
    else:
        out = sys.argv[3]; pats = sys.argv[4:] or ['*']; n = 0
        for name in P.files:
            if any(fnmatch.fnmatch(name.lower(), p.lower()) for p in pats):
                dst = os.path.join(out, name.replace('\\', '/')); os.makedirs(os.path.dirname(dst), exist_ok=True)
                open(dst, 'wb').write(P.read(name)); n += 1
        print('extracted', n, file=sys.stderr)
