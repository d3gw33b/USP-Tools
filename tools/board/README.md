# usp-board

`usp-board` is the `board` command from
[collaborative-ai-workboard](https://github.com/ed-slopper/collaborative-ai-workboard), adapted so that
code reaches `main` only through a pull request and its vote. Claiming a row still works at once.

## What the change is

Upstream, `board land` pushes your code straight to `main`. Here:

| Step | Command | What reaches GitHub |
|---|---|---|
| Take a row | `usp-board claim P2 --who you/claude` | A one-line change to `WORK.md` on `main`, so nobody else can take it |
| Work | `usp-board commit P2 -m "..."` | Nothing yet; it stays on your machine |
| Finish | `usp-board done P2 --gap "what's left"` | Nothing yet |
| Hand in | `usp-board submit` | A branch `row/p2` and a pull request with a board block in its description |
| Merged | the `board-done` Action runs `usp-board finish-pr` | P2 moves to Done with the merge commit, and each gap becomes a new row |

Other changes:

- Every commit the board makes by itself (claim, release, add, decide, done) carries the contributor
  agreement line. Upstream builds those commits without running the commit hook, so they missed it.
- `usp-board decide H1 "the answer"` records an owner decision and moves the `humans` row to Done.
- `usp-board guard` lists commits pushed straight to `main` that change more than `WORK.md`. The
  `board-guard` Action turns that into a red mark on `main`.
- New change-log lines go after a wrapped entry, not into the middle of it.
- `usp-board land` is refused, with a pointer to `submit`.

Every other command (`status`, `next`, `show`, `release`, `add`, `pending`, `check`, `chart`) is the
workboard's own, unchanged.

## Install

The workboard has no licence yet, so its code isn't copied here. Install it from one pinned commit, and
`usp-board` imports it:

```
python -m pip install -r requirements.txt   # includes the pinned workboard
python tools/board/usp_board.py status      # or alias usp-board to that
```

Run it from inside the project's clone (the folder with `WORK.md`).

## Handing in work

`usp-board submit` rebases your commits onto the newest `main`, pushes them as `row/<ids>`, and opens the
pull request with `gh` if you have it. Without `gh`, it prints the link that opens the pull request and the
description to paste. Keep the ```` ```usp-board ```` block in the description: it's how the rows find
their way to Done after the merge.

```usp-board
done: P2
summary P2: planet weather parameters, bit-exact
gap P2: storm frequency table is untested
```

If the vote asks for changes, commit them and run `usp-board submit` again. It updates the same branch
and pull request. A pull request without the block still works if its title starts with the row IDs
(`P2: ...` or `P2, P3: ...`), but its gaps aren't added.

## In a project repo

Copy `examples/board-done.yml` and `examples/board-guard.yml` into the project's `.github/workflows/`.
`board-done` needs `contents: write`. `board-guard` treats merge commits as pull requests, so merge pull
requests with a merge commit, not a squash.

## Tests

```
python -m unittest tools/board/test_usp_board.py
```

They make a throwaway git remote and run claim, submit, finish-pr, decide and guard against it.
