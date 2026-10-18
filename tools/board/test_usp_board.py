"""Tests for usp-board against a real git remote: python -m unittest tools/board/test_usp_board.py"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import usp_board  # noqa: E402

AGREEMENT = usp_board.AGREEMENT
BOARD = """# Board

## H Decisions

| ID | Task | Area | Needs | Who | Notes |
|---|---|---|---|---|---|
| H1 | Pick the units | humans | | | |

## F Foundations

| ID | Task | Area | Needs | Who | Notes |
|---|---|---|---|---|---|
| F1 | Add a tool | any | | | |
| F2 | Add another tool | any | | | |

## Done

| ID | Task | Section | Who | Date | Commit |
|---|---|---|---|---|---|

## Changes to the board

- 2026-10-16 board drafted. This first entry is long and
  wraps onto a second line.
"""
HOOK = f"""#!/bin/sh
grep -qx '{AGREEMENT}' "$1" || printf '\\n%s\\n' '{AGREEMENT}' >> "$1"
"""


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def ub(cwd, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, "usp_board.py"), *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, "WORKBOARD_WHO": "ann/claude"})


class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.remote = os.path.join(t, "remote.git")
        git(t, "init", "--quiet", "--bare", "-b", "main", self.remote)
        seed = os.path.join(t, "seed")
        git(t, "clone", "--quiet", self.remote, seed)
        self._identity(seed)
        os.makedirs(os.path.join(seed, "hooks"))
        with open(os.path.join(seed, "hooks", "commit-msg"), "w") as f:
            f.write(HOOK)
        os.chmod(os.path.join(seed, "hooks", "commit-msg"), 0o755)
        for name, text in (("WORK.md", BOARD), ("workboard.toml", 'branch = "main"\n'), ("code.txt", "v1\n")):
            with open(os.path.join(seed, name), "w", newline="\n") as f:
                f.write(text)
        git(seed, "add", ".")
        git(seed, "commit", "--quiet", "-m", f"start\n\n{AGREEMENT}")
        git(seed, "push", "--quiet", "origin", "main")
        self.a = self._clone("a")

    def tearDown(self):
        self.tmp.cleanup()

    def _identity(self, d):
        git(d, "config", "user.name", "test")
        git(d, "config", "user.email", "test@example.invalid")

    def _clone(self, name):
        d = os.path.join(self.tmp.name, name)
        git(self.tmp.name, "clone", "--quiet", self.remote, d)
        self._identity(d)
        git(d, "config", "core.hooksPath", "hooks")
        return d

    def remote_board(self):
        git(self.a, "fetch", "--quiet")
        return git(self.a, "show", "origin/main:WORK.md")

    def ok(self, p):
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def test_claim_carries_agreement_and_log_goes_after_wrapped_entry(self):
        self.ok(ub(self.a, "claim", "F1"))
        git(self.a, "fetch", "--quiet")
        self.assertIn(AGREEMENT, git(self.a, "log", "-1", "--format=%B", "origin/main"))
        log = self.remote_board().split("## Changes to the board")[1].strip().splitlines()
        self.assertTrue(log[1].startswith("  wraps"), log)
        self.assertIn("claim F1", log[2])

    def test_land_is_refused(self):
        p = ub(self.a, "land")
        self.assertEqual(p.returncode, 2)
        self.assertIn("submit", p.stderr)

    def test_submit_pushes_a_branch_and_leaves_main_alone(self):
        self.ok(ub(self.a, "claim", "F1"))
        with open(os.path.join(self.a, "code.txt"), "w") as f:
            f.write("v2\n")
        git(self.a, "add", "code.txt")
        self.ok(ub(self.a, "commit", "F1", "-m", "add the tool"))
        out = self.ok(ub(self.a, "done", "F1", "--summary", "tool added", "--gap", "write its docs"))
        self.assertIn("usp-board submit", out)
        out = self.ok(ub(self.a, "submit", "--no-gh"))
        self.assertIn("row/f1", out)
        self.assertIn("```usp-board\ndone: F1\nsummary F1: tool added\ngap F1: write its docs\n```", out)
        self.assertEqual(git(self.a, "show", "origin/row/f1:code.txt"), "v2")
        self.assertEqual(git(self.a, "show", "origin/main:code.txt"), "v1")
        self.assertNotIn("| F1 | tool added", self.remote_board())

    def test_finish_pr_moves_rows_and_adds_gaps(self):
        self.ok(ub(self.a, "claim", "F1"))
        body = os.path.join(self.tmp.name, "body.md")
        with open(body, "w") as f:
            f.write("Text\n\n```usp-board\ndone: F1\nsummary F1: tool added\ngap F1: write its docs\n```\n")
        ci = self._clone("ci")
        out = self.ok(ub(ci, "finish-pr", "--commit", "abcdef1234", "--body-file", body, "--pr", "9"))
        self.assertIn("F3", out)
        b = self.remote_board()
        self.assertIn("| F1 | tool added | F | ann/claude |", b)
        self.assertIn("| F3 | write its docs | any |  |  | Gap of F1 |", b)
        self.assertIn("F1 done; added F3 (gaps) (#9).", b)
        git(ci, "fetch", "--quiet")
        self.assertIn(AGREEMENT, git(ci, "log", "-1", "--format=%B", "origin/main"))
        # running it again (a re-run job) changes nothing
        self.ok(ub(ci, "finish-pr", "--commit", "abcdef1234", "--body-file", body))
        self.assertEqual(b, self.remote_board())

    def test_finish_pr_falls_back_to_the_title(self):
        ci = self._clone("ci")
        self.ok(ub(ci, "finish-pr", "--commit", "abcdef1", "--title", "F1, F2: two tools"))
        b = self.remote_board()
        self.assertIn("| F1 | Add a tool | F |", b)
        self.assertIn("| F2 | Add another tool | F |", b)

    def test_decide_records_an_owner_decision(self):
        self.ok(ub(self.a, "decide", "H1", "metres", "--who", "owner"))
        self.assertIn("| H1 | metres | H | owner |", self.remote_board())
        self.assertEqual(ub(self.a, "decide", "F2", "no").returncode, 2)

    def test_guard_flags_direct_code_pushes_only(self):
        start = git(self.a, "rev-parse", "HEAD")
        self.ok(ub(self.a, "claim", "F1"))  # board-only: fine
        git(self.a, "pull", "--quiet", "--rebase")
        git(self.a, "checkout", "--quiet", "-b", "feature")
        with open(os.path.join(self.a, "code.txt"), "w") as f:
            f.write("v2\n")
        git(self.a, "commit", "--quiet", "-am", "via a pull request")
        git(self.a, "checkout", "--quiet", "main")
        git(self.a, "merge", "--quiet", "--no-ff", "-m", "Merge pull request #1", "feature")  # fine
        self.assertEqual(ub(self.a, "guard", "--before", start).returncode, 0)
        with open(os.path.join(self.a, "code.txt"), "w") as f:
            f.write("v3\n")
        git(self.a, "commit", "--quiet", "-am", "straight to main")
        p = ub(self.a, "guard", "--before", start)
        self.assertEqual(p.returncode, 1)
        self.assertIn("straight to main (code.txt)", p.stdout)


class Parsing(unittest.TestCase):
    def test_block_and_title(self):
        info = usp_board.parse_block("x\n```usp-board\ndone: P2, P3a\nsummary P2: names\ngap P3a: caves\n```\n")
        self.assertEqual(info["done"], ["P2", "P3a"])
        self.assertEqual(info["summary"], {"P2": "names"})
        self.assertEqual(info["gaps"], {"P3a": ["caves"]})
        self.assertEqual(usp_board.title_rows("P2, P3a: two rows"), ["P2", "P3a"])
        self.assertEqual(usp_board.title_rows("Fix the README"), [])

    def test_agreement_added_once(self):
        once = usp_board.with_agreement("claim F1")
        self.assertEqual(usp_board.with_agreement(once), once)


if __name__ == "__main__":
    unittest.main()
