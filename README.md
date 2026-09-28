# kuGPT

Local, system-wide writing correction for Windows. kuGPT fixes common spelling mistakes, capitalizes sentences, and adds conservative punctuation in desktop applications without sending or storing what you type.

## Install

Open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/cyberythem/kuGPT/main/install.ps1 | iex
```

The installer uses Windows' built-in .NET Framework compiler, creates one local executable, starts it, and enables it at sign-in. No Python, Node.js, Rust, account, API key, or cloud service is required.

> The repository must be public for the one-line installer to work without GitHub authentication.

## Use

```powershell
kugpt status
kugpt pause
kugpt resume
kugpt stop
kugpt start
kugpt doctor
kugpt uninstall
```

Undo the most recent automatic correction with `Ctrl+Alt+Backspace`.

Examples:

- `teh ` becomes `The ` at the beginning of a sentence.
- `i dont ` becomes `I don't `.
- Pressing Enter after an unfinished sentence adds a period.
- Typing two spaces after three or more words changes the first space to `. `.
- `should of ` becomes `should have ` using the previous word as context.

## Privacy and safety

- Text is held only in a short in-memory buffer.
- kuGPT writes no typing history and makes no network requests.
- The buffer is cleared whenever the focused window changes.
- Standard Windows password inputs and common password-manager processes are excluded.
- Corrections are deliberately conservative and can be undone immediately.

Browser-rendered password fields cannot always be identified through the Windows API. Pause kuGPT before entering secrets in an application you do not trust to expose password-field metadata.

## Current scope

Version 0.1 is a Windows-first English MVP. It uses a high-confidence correction dictionary and one contextual grammar rule. Broader dictionaries, user configuration, additional languages, and an optional local context model are planned after the keyboard pipeline has been validated across applications.

## Build and test

No downloaded dependencies are needed:

```powershell
.\build.ps1 -Test
.\dist\kugpt.exe doctor
```

## Contributing

Issues and pull requests are welcome. Please keep the core offline by default and avoid adding telemetry or cloud dependencies.

