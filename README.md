# translate-panel

A macOS floating translation panel — select text with [PopClip](https://www.popclip.app/), click the globe icon, and a Google Translate panel pops up inline without opening a new browser tab.

## How it works

- PopClip triggers a shell script with the selected text
- A small floating window (pywebview / WebKit) opens `translate.google.com` with the text pre-filled
- The panel stays on top of other windows; close it when done

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

## Usage

1. Select any text in any app
2. PopClip bar appears — click the **globe** icon
3. A 720×520 floating panel opens with the translation

## Manual usage (without PopClip)

```bash
translate-panel "hello world"
```
