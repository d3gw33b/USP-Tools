# USP review bot

Posts a review card for every pull request into a Discord voting channel, counts votes, and takes `!usp` commands.
GitHub Actions does the work every 15 minutes. To make the bot show as online and answer instantly, run
`usp_live.py` on a computer that stays on (see below).

- **`review-card` workflow:** on each pull request, it runs an automatic risk check and writes a plain-English AI
  summary with a free model on GitHub's machine. Then it posts the card with ✅ ➖ ❌ reactions. Mod chat gets a notice only
  when others can vote; votes only the owners decide ping the owners in the voting channel instead.
- **`vote-counter` workflow:** every 15 minutes, it reads `!usp` commands and reactions, and posts decisions.
- **`bot-selftest` workflow:** run it by hand to check a model works.
- **`bot-live-check` workflow:** run it by hand to check the live bot connects (it stays online for 90 seconds).

Settings are kept in a readable card the bot pins in the settings channel. Change them only with `!usp` commands.

## Size tiers (defaults; change with `!usp tier`)

| Tier | Changed lines | Vote timer | Decided by |
|---|---|---|---|
| tiny | up to 20 | 5 min | passes unless more ❌ than ✅ (an owner's ✅ passes it at once) (`!usp vote` makes it a majority vote) |
| small | up to 100 | 15 min | same as tiny |
| medium | up to 500 | 6 h | majority of votes cast; no votes → owners |
| large | up to 2000 | 24 h | one owner ✅ |
| very large | more | 48 h | both owners ✅ |

Changes to `.github` count as very large. License/rules/README changes and binary-looking files count as at least large.
Pull requests opened by an owner skip the vote: the card is posted for information only. The repository owner always
counts as an owner; add more GitHub accounts with `!usp github-owners add <name>`.
An owner's ❌ is a veto at any tier. A vote ends when every voter has voted or the timer runs out.
The bot never merges. An owner merges or closes on GitHub.

## Secrets (in each repo that uses it)

- `DISCORD_BOT_TOKEN`: the bot's token.
- `DISCORD_OWNER_IDS`: owners' Discord user IDs, comma-separated.
- `DISCORD_CHANNEL_IDS`: `mod=<id>,voting=<id>,settings=<id>`.
- `GEMINI_API_KEY`: optional, only for Gemini models.

The bot keeps a pinned help card with every command in the settings channel and updates it when the bot changes.

## Override

Owners can change how votes are decided without touching the defaults, and switch it off again:
`!usp override <size> <how>` with sizes `small`, `medium`, `large`, `huge`, `all`, `owners`, and how `auto`, `easy`,
`vote`, `owner` or `both`. `!usp override medium time 1h` sets a different timer. `!usp override off` or `on` pauses or
resumes overrides, and `!usp override clear` removes them. Open votes switch to a new rule straight away.

## Online and instant: `usp_live.py`

1. Install Python 3.11 or newer.
2. Copy `bot.env.example` to `bot.env` (next to `usp_live.py`) and fill in the same three values as the secrets:
   ```
   DISCORD_BOT_TOKEN=...
   DISCORD_OWNER_IDS=...
   DISCORD_CHANNEL_IDS=mod=...,voting=...,settings=...
   ```
   `bot.env` is in `.gitignore`. Never commit it.
3. Run `python usp_live.py` (on Windows, double-click `start-bot.bat`). The bot shows as online, answers commands instantly and decides votes the moment the
   last voter reacts. Close it and the 15-minute check takes over again within about 3 minutes.

On Windows, `autostart-on.bat` runs it in the background now and at every login (log in `bot.log`), and
`autostart-off.bat` stops it and turns that off. Only one copy runs per computer; `python usp_live.py --stop` stops it.
