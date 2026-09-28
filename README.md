# kuGPT

Private, local writing correction for Windows. kuGPT corrects spelling with a SymSpell-style engine, capitalizes sentences, and adds conservative punctuation through a system-wide keyboard hook.

Live correction and undo have been verified in Notepad. Other apps, including WhatsApp and Microsoft Office, still need compatibility testing; do not assume they work identically.

Everything typed is processed in a short in-memory buffer. There is no account, API key, telemetry, cloud model, or stored typing history.

## Install

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/cyberythem/kuGPT/main/install.ps1 | iex
```

The installer downloads Python's official signed embedded runtime and the pinned SymSpell English frequency dictionary, verifies both, enables kuGPT at sign-in, and starts it. You do **not** need Python installed.

## Test it

Open a new PowerShell window:

```powershell
kugpt doctor
kugpt fix i am nto tehe ncie pesron
kugpt status
```

The second command must print:

```text
I am not the nice person
```

Then type `i am nto tehe ncie pesron ` in a fresh Notepad tab. It should become `I am not the nice person ` as each word boundary is reached. Try other apps in a disposable draft first. If typing misbehaves, run `kugpt stop` immediately.

## Commands

```powershell
kugpt start
kugpt stop
kugpt restart
kugpt status
kugpt pause
kugpt resume
kugpt doctor
kugpt check nto tehe ncie pesron
kugpt fix i am nto tehe ncie pesron
kugpt uninstall
```

Undo the most recent live correction with `Ctrl+Alt+Backspace`.

## Current behavior

- Corrects high-confidence English misspellings at a space, punctuation mark, or Enter.
- Capitalizes the first word after startup, a window change, or `.`, `!`, and `?`.
- Two spaces after a sentence of at least three words produce a period and one space.
- Enter adds a period to an unfinished sentence.
- Includes a few context rules, such as `should of` to `should have`.
- Recognizes every word in the 82,000+ word dictionary and indexes the 25,000 most frequent correction candidates.

Automatic correction is deliberately conservative. A deeper local context model, Hunspell language packs, per-app exclusions, and automatic language switching belong in later releases.

## Privacy and safety

- The current word and short sentence state exist only in memory.
- The buffer clears whenever the focused window changes.
- Standard Windows password inputs and common password-manager processes are excluded.
- Browser-rendered password fields cannot always be identified through Windows APIs. Pause kuGPT before entering secrets in an app that does not expose password metadata.
- The installer does not disable or bypass Windows Security.

## Development

Python 3.10+ is enough for development:

```powershell
.\build.ps1 -Test
python kugpt_launcher.py doctor
```

The end-user installer remains self-contained and does not use the developer's Python installation.

## Contributing

Issues and pull requests are welcome. Keep the correction core offline by default and do not add telemetry.

