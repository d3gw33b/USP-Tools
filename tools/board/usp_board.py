"""usp-board: the `board` command from collaborative-ai-workboard, adapted to projects where code only
reaches main through a pull request and a vote.

It imports the pinned workboard package (see tools/board/README.md); none of its code is copied here.
What it changes:
- Board-only commits (claim, release, add, decide, finish-pr) carry the contributor agreement line.
- `land` is replaced by `submit`: push the finished rows' branch and open a pull request.
- `decide ID "answer"` records an owner decision on a `humans` row.
- `finish-pr` moves a merged pull request's rows to Done (run by a GitHub Action after the merge).
- `guard` lists direct pushes to main that change more than the board (for a CI warning).
- New change-log lines go after a wrapped entry, not into the middle of it.
Every other command is passed to `board` unchanged.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

try:
    from workboard import cli
    from workboard.board import Board, BoardError, today
    from workboard.config import load
    from workboard.gitops import Git
except ModuleNotFoundError:
    sys.exit("usp-board needs the pinned workboard package: see tools/board/README.md")

AGREEMENT = "Agreed-to: CONTRIBUTING.md#contributor-agreement"
ROW_ID = r"[A-Z][A-Z0-9]*\d+[a-z]?"
BLOCK = re.compile(r"```usp-board\s*\n(.*?)```", re.S)


# ------------------------------------------------------------------ patches
def with_agreement(message: str) -> str:
    lines = message.rstrip("\n").split("\n")
    return message if AGREEMENT in lines else message.rstrip("\n") + "\n\n" + AGREEMENT + "\n"


_commit_file_on = Git._commit_file_on


def _commit_file_on_agreed(self, parent, path, content, message):
    # Board-only commits are built with commit-tree, which runs no hooks.
    return _commit_file_on(self, parent, path, content, with_agreement(message))


def _log_after_wrapped(self, text, who, date=None):
    if self.log_start < 0:
        return
    at = self.log_last + 1
    while at < len(self.lines) and self.lines[at][:1] in (" ", "\t") and self.lines[at].strip():
        at += 1  # continuation lines of the last entry
    self.lines.insert(at, f"- {date or today()} {who}: {text}")
    self._parse()


Git._commit_file_on = _commit_file_on_agreed
Board.log = _log_after_wrapped


# ------------------------------------------------------------------ helpers
def _who(cfg, args) -> str:
    return cli._who(cfg, args)


def _repo_url(git: Git) -> str:
    url = git.out("remote", "get-url", git.remote, check=False)
    m = re.match(r"(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:)(.+?)(?:\.git)?/?$", url)
    return f"https://github.com/{m.group(1)}" if m else ""


def parse_block(body: str) -> dict:
    """The rows a pull request finishes, from its ```usp-board block:
    `done: P2, P3`, `summary P2: text`, `gap P2: text` (one per line)."""
    out = {"done": [], "summary": {}, "gaps": {}}
    for block in BLOCK.findall(body or ""):
        for line in block.splitlines():
            line = line.strip()
            if m := re.match(r"done:\s*(.+)$", line):
                out["done"] += [r for r in re.findall(ROW_ID, m.group(1)) if r not in out["done"]]
            elif m := re.match(rf"summary\s+({ROW_ID}):\s*(.+)$", line):
                out["summary"][m.group(1)] = m.group(2).strip()
            elif m := re.match(rf"gap\s+({ROW_ID}):\s*(.+)$", line):
                out["gaps"].setdefault(m.group(1), []).append(m.group(2).strip())
    return out


def title_rows(title: str) -> list[str]:
    """Row IDs at the start of a pull request title: `P2: ...` or `P2, P3: ...`."""
    m = re.match(rf"\s*((?:{ROW_ID})(?:\s*,\s*{ROW_ID})*)\s*:", title or "")
    return re.findall(ROW_ID, m.group(1)) if m else []


def pr_body(entries: list[dict]) -> str:
    lines = ["```usp-board", "done: " + ", ".join(e["id"] for e in entries)]
    for e in entries:
        if e["summary"]:
            lines.append(f"summary {e['id']}: {e['summary']}")
        lines += [f"gap {e['id']}: {g}" for g in e["gaps"]]
    lines.append("```")
    return ("What this does:\n\n"
            + "\n".join(f"- **{e['id']}**: {e['summary'] or '(see commits)'}" for e in entries)
            + "\n\nWhen this is merged, the rows below move to Done on the board and each gap becomes a new row.\n\n"
            + "\n".join(lines) + "\n")


# ----------------------------------------------------------------- commands
def cmd_land(cfg, args) -> int:
    raise BoardError("`land` pushes straight to main here. Use `usp-board submit`, which opens a pull request.")


def cmd_submit(cfg, args) -> int:
    """Push the finished rows' work as a branch and open a pull request. WORK.md is not touched:
    the rows move to Done when the pull request is merged."""
    git = cli._git(cfg)
    if git.dirty():
        raise BoardError("there are uncommitted changes; commit or stash them, then submit again")
    git.fetch()
    remote_board = Board(git.show(git.upstream, cfg.board), cfg.decision_areas, cfg.done_heading, cfg.log_heading)
    entries = []
    for e in git.journal():
        try:
            if remote_board.find(e["id"]).done:
                continue  # merged already
        except BoardError:
            continue
        entries.append(e)
    git.save_journal(entries)
    if not entries:
        print("nothing to submit; `usp-board done ID` marks a finished row")
        return 0
    p = git.run("rebase", "--quiet", git.upstream, check=False)
    if p.returncode:
        raise BoardError("your commits conflict with main. Resolve the conflict, `git rebase --continue`, "
                         "then submit again.\n" + (p.stderr or p.stdout).strip())
    if not git.out("rev-list", f"{git.upstream}..HEAD"):
        raise BoardError("there are no commits to submit on top of main")
    ids = [e["id"] for e in entries]
    branch = args.branch or "row/" + "-".join(ids).lower()
    git.run("push", "--quiet", "--force-with-lease", git.remote, f"HEAD:refs/heads/{branch}")
    first = entries[0]["summary"] or remote_board.find(ids[0]).task
    title = args.title or f"{', '.join(ids)}: {first}"
    body = pr_body(entries)
    if shutil.which("gh") and not args.no_gh:
        cmd = ["gh", "pr", "create", "--base", git.branch, "--head", branch, "--title", title, "--body", body]
        p = subprocess.run(cmd + (["--draft"] if args.draft else []), cwd=cfg.root, text=True, capture_output=True)
        if p.returncode == 0:
            print(f"pushed {branch} and opened {p.stdout.strip()}")
            return 0
        if "already exists" in p.stderr:
            print(f"pushed {branch}; its pull request already exists and now has the new commits")
            return 0
        print(f"gh could not open the pull request: {p.stderr.strip()}", file=sys.stderr)
    url = _repo_url(git)
    print(f"pushed {branch}. Open the pull request here:")
    print(f"  {url}/compare/{git.branch}...{branch}?expand=1" if url else f"  (branch {branch} on {git.remote})")
    print(f"\nTitle:\n  {title}\n\nDescription (paste it whole; the board block is read when it merges):\n\n{body}")
    return 0


def cmd_decide(cfg, args) -> int:
    """Record an owner decision on a `humans` row and move it to Done."""
    who, date = _who(cfg, args), today()

    def change(text):
        b = cli._board(cfg, text)
        row = b.find(args.id)
        if row.done:
            raise BoardError(f"{args.id} is already done")
        if row.get("area").lower() not in b.decision_areas:
            raise BoardError(f"{args.id} is not a decision row; finish it through a pull request")
        b.finish(args.id, "", who=who, date=date, summary=args.answer)
        b.log(f"{args.id} decided: {args.answer}.", who, date)
        return b.text, f"{args.id}: decided by {who}", None

    cli._change(cfg, change, "decide")
    print(f"{args.id} recorded as decided")
    return 0


def cmd_finish_pr(cfg, args) -> int:
    """Move a merged pull request's rows to Done with the merge commit, adding its gaps as rows."""
    body = open(args.body_file, encoding="utf-8").read() if args.body_file else ""
    info = parse_block(body)
    ids = info["done"] or title_rows(args.title or "")
    if not ids:
        print("this pull request names no board rows; nothing to do")
        return 0
    commit = args.commit[:7]

    def change(text):
        b = cli._board(cfg, text)
        moved, added, owner = [], [], ""
        for rid in ids:
            try:
                row = b.find(rid)
            except BoardError as e:
                print(f"skipped: {e}")
                continue
            if row.done:
                continue
            owner = owner or row.who.split(" (")[0]
            b.finish(rid, commit, summary=info["summary"].get(rid))
            moved.append(rid)
            for gap in info["gaps"].get(rid, []):
                added.append(b.add(row.section, gap, notes=f"Gap of {rid}"))
        if not moved:
            raise BoardError("every row named here is already done")
        note = f"{', '.join(moved)} done"
        if added:
            note += f"; added {', '.join(added)} (gaps)"
        b.log(note + (f" (#{args.pr})" if args.pr else "") + ".", owner or _who(cfg, args))
        return b.text, f"done {', '.join(moved)}", (moved, added)

    try:
        moved, added = cli._change(cfg, change, "done")
    except BoardError as e:
        if "already done" in str(e):
            print(e)
            return 0
        raise
    print(f"moved {', '.join(moved)} to Done at {commit}" + (f"; new rows {', '.join(added)}" if added else ""))
    return 0


def cmd_guard(cfg, args) -> int:
    """List commits on main's first-parent line that are not merges and change more than the board."""
    git = cli._git(cfg)
    rng = f"{args.before}..{args.after}" if args.before and set(args.before) != {"0"} else args.after
    bad = []
    for sha in git.out("rev-list", "--first-parent", rng).split():
        if len(git.out("rev-list", "--parents", "-n", "1", sha).split()) > 2:
            continue  # a merged pull request
        files = [f for f in git.out("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).split("\n") if f]
        if any(f != cfg.board for f in files):
            bad.append((sha[:7], git.out("log", "-1", "--format=%an: %s", sha), files))
    for sha, what, files in bad:
        print(f"{sha} {what} ({', '.join(files[:5])}{', ...' if len(files) > 5 else ''})")
    return 1 if bad else 0


# --------------------------------------------------------------------- main
OWN = {"land", "submit", "decide", "finish-pr", "guard"}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="usp-board", description=__doc__.split("\n\n")[0])
    p.add_argument("-C", dest="dir", default=".", help="run as if started in this folder")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="command")
    sp = sub.add_parser("submit", help="Push your finished rows as a branch and open a pull request.")
    sp.add_argument("--title")
    sp.add_argument("--branch", help="branch name (default: row/<ids>)")
    sp.add_argument("--draft", action="store_true")
    sp.add_argument("--no-gh", action="store_true", help="don't use the gh command; print the link instead")
    sp.set_defaults(fn=cmd_submit)
    sp = sub.add_parser("decide", help="Record an owner decision on a humans row.")
    sp.add_argument("id")
    sp.add_argument("answer")
    sp.add_argument("--who")
    sp.set_defaults(fn=cmd_decide)
    sp = sub.add_parser("finish-pr", help="Move a merged pull request's rows to Done (for CI).")
    sp.add_argument("--commit", required=True, help="the merge commit")
    sp.add_argument("--body-file", help="file holding the pull request's description")
    sp.add_argument("--title", help="the pull request's title")
    sp.add_argument("--pr", help="the pull request's number, for the change log")
    sp.add_argument("--who")
    sp.set_defaults(fn=cmd_finish_pr)
    sp = sub.add_parser("guard", help="List direct pushes to main that change more than the board (for CI).")
    sp.add_argument("--before", help="the commit main was at before the push")
    sp.add_argument("--after", default="HEAD")
    sp.set_defaults(fn=cmd_guard)
    sub.add_parser("land", help="Not used here: see submit.").set_defaults(fn=cmd_land)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    i = 2 if argv[:1] == ["-C"] else 0
    if not argv[i:] or argv[i] not in OWN:
        rc = cli.main(argv)  # every other command is the workboard's own
        if rc == 0 and argv[i:i + 1] == ["done"]:
            print("Here, publish with `usp-board submit`, not `board land`.")
        return rc
    args = parser().parse_args(argv)
    try:
        return args.fn(load(args.dir), args)
    except BoardError as e:
        print(f"usp-board: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
