# Contributing to USP tools

## Setup (once per clone)

```
git config core.hooksPath tools/hooks
```

This adds the agreement line to every commit you make.

## How to contribute

1. Fork the repo and create a branch.
2. Make a focused change. Keep tools general; don't add anything that depends on a specific game's data.
3. Make sure `python -m py_compile` passes on the files you changed.
4. Open a pull request. One maintainer approval is required before merge.

## Ground rules

- No game files, decompiled code, extracted data, or recorded outputs, in code, issues or pull requests.
- No personal paths, usernames, emails, or keys.
- Public discussion is fine. Bug reports should describe the steps without attaching game data.

## Contributor agreement

By submitting a contribution (commit, patch or pull request) to USP tools, you agree that:

1. You wrote it yourself (or with an AI tool you directed) and have the right to submit it.
2. It contains no files, code or data copied from any game.
3. You license it to the project under GPL-3.0-or-later, **and** you grant the project owner (GitHub
   user `d3gw33b`) a permanent, worldwide, royalty-free right to relicense your contribution under any
   other license, including a closed one.

You keep the copyright to your work.

**Every commit** must end with this exact line, or the check rejects it:

    Agreed-to: CONTRIBUTING.md#contributor-agreement

The local hook above adds it for you. A GitHub check rejects any push or pull request with a commit missing it.
