# translate-panel

A macOS floating Google Translate panel for [PopClip](https://www.popclip.app/) — select text, click the globe, a panel appears inline without opening a browser tab.

## How it works

```
PopClip → trigger.py ──socket──▶ daemon.py (persistent)
                                      │
                                   WebKit window (pre-warmed)
                                   shows / hides on demand
```

- A daemon keeps a **pre-warmed WebKit window** in the background, so the panel appears instantly.
- The window is **floating** (`on_top`) and **auto-hides** when you click back into any other app.
- PopClip's loading spinner stops as soon as trigger.py sends the text — not when the window closes.

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

The install script registers a **launch agent** so the daemon starts at login and is always ready.

## Usage

Select any text → PopClip → **globe icon** → floating translation panel appears.

Click anywhere outside the panel to dismiss it.

## Manual usage

```bash
translate-panel "hello world"
```

## Logs

```bash
tail -f ~/.local/share/translate-panel/daemon.log
```
