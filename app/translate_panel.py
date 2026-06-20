#!/usr/bin/env python3
"""
translate-panel: open selected text in a floating Google Translate panel.
Usage: translate_panel.py [text]
"""
import sys
import urllib.parse
import webview


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else ""
    encoded = urllib.parse.quote(text)
    url = (
        f"https://translate.google.com/?sl=auto&tl=zh-CN"
        f"&text={encoded}&op=translate"
    )

    window = webview.create_window(
        "Translate Panel",
        url,
        width=720,
        height=520,
        on_top=True,
        resizable=True,
    )
    webview.start()


if __name__ == "__main__":
    main()
