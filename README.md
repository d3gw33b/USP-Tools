# USP tools

Public, general-purpose tools for working on a Windows executable's functions and on packed game archives.

**This repo contains no game code, data, or recorded outputs.** Every tool reads a file you already own, at runtime.

## Tools

| Tool | What it does |
|---|---|
| `tools/difftest/nmsemu.py` | Runs one function from a Windows `.exe` inside a small emulator (unicorn), so you can call it with your own inputs. |
| `tools/difftest/asm.py` | Disassembles a function from a `.exe` and follows its jumps. Set `PE_EXE` to your file, and optionally `SYMBOL_CSV` to a symbol list you keep locally. |
| `tools/hgpak.py` | Lists and extracts files from HGPAK archives. Needs `zstandard`. |

## Setup

```
python -m pip install -r requirements.txt
export PE_EXE=/path/to/your/file.exe
python tools/difftest/asm.py 0x140001000
python tools/hgpak.py list /path/to/archive.pak
```

## Rules

- Never commit game files, extracted data, recorded outputs, or screenshots. `.gitignore` blocks the common ones.
- Anything you record from a game stays on your own machine.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) first. It includes the contributor agreement that every commit must carry.

## License

[GPL-3.0-or-later](LICENSE). Contributors accept the [contributor agreement](CONTRIBUTING.md#contributor-agreement), which lets the project owner relicense the project later.

No affiliation with or endorsement by Hello Games.
