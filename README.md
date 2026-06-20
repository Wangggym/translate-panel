# translate-panel

A macOS floating Google Translate panel for [PopClip](https://www.popclip.app/) — select text, click the icon, a panel appears inline without opening a browser tab.

## Features

- **Instant panel** — a persistent daemon keeps a pre-warmed WebKit window ready; no cold-start delay after the first load
- **Floating** — `on_top` window stays above other apps
- **Auto-hide** — click anywhere outside the panel and it disappears
- **Audio stops on hide** — if Google Translate TTS is playing, it stops when the panel hides
- **No Dock icon** — runs silently in the background

## How it works

```
PopClip → trigger.py ──socket──▶ daemon.py (persistent)
                                      │
                                   WKWebView (Google Translate)
                                   injects text via URL params + popstate
                                   shows / hides on demand
```

Text injection uses `history.replaceState(?text=…)` + `popstate` dispatch, working with Google Translate's own SPA router — no custom UI, no API key, no cost.

## Requirements

- macOS 12+
- Python 3.9+
- [PopClip](https://www.popclip.app/)

## Install

```bash
chmod +x install.sh
./install.sh
```

Then double-click `popclip/TranslatePanel.popclipext` to install the PopClip extension.

The install script:
- Creates a Python venv with `pywebview` + `pyobjc`
- Symlinks `app/daemon.py` and `app/trigger.py` into `~/.local/share/translate-panel/` — code changes take effect without reinstall
- Registers a **launch agent** so the daemon starts at login

## Usage

Select any text → PopClip → translation icon → floating panel appears.

Click anywhere outside the panel to dismiss it. TTS audio stops automatically.

## After code changes

No reinstall needed — just restart the daemon:

```bash
pkill -f daemon.py   # launchd restarts it automatically
```

## Manual usage

```bash
translate-panel "hello world"
```

## Logs

```bash
tail -f ~/.local/share/translate-panel/daemon.log
```

## Regression tests

```bash
python3 test_audio.py
```

See `tests/cases/` for documented E2E scenarios and known pitfalls.
