#!/usr/bin/env python3
"""
translate-panel daemon — keeps a WebKit window pre-warmed and serves text via Unix socket.
"""
import os
import sys
import json
import socket
import threading
import urllib.parse
import webview

DATA_DIR = os.path.expanduser("~/.local/share/translate-panel")
SOCKET_PATH = os.path.join(DATA_DIR, "daemon.sock")
PID_FILE = os.path.join(DATA_DIR, "daemon.pid")
BASE_URL = "https://translate.google.com/?sl=auto&tl=zh-CN&op=translate"

_window = None

# Injected after every page load: zoom + blur-to-hide
INJECT_JS = """
document.documentElement.style.zoom = '85%';
(function setup() {
    if (window.pywebview && window.pywebview.api) {
        window.addEventListener('blur', function() {
            pywebview.api.on_blur();
        });
    } else {
        setTimeout(setup, 50);
    }
})();
"""


class Api:
    def on_blur(self):
        if _window:
            _window.hide()


def make_url(text: str) -> str:
    if text.strip():
        return (
            "https://translate.google.com/?sl=auto&tl=zh-CN"
            f"&text={urllib.parse.quote(text)}&op=translate"
        )
    return BASE_URL


def handle_client(conn):
    try:
        data = b""
        while chunk := conn.recv(4096):
            data += chunk
        req = json.loads(data.decode())
        text = req.get("text", "")
        if _window:
            _window.load_url(make_url(text))
            try:
                from AppKit import NSApp
                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass
            _window.show()
    except Exception as e:
        print(f"daemon: handle_client error: {e}", file=sys.stderr)
    finally:
        conn.close()


def socket_server():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
        srv.bind(SOCKET_PATH)
        srv.listen(5)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=handle_client, args=(conn,), daemon=True).start()


def on_loaded():
    if _window:
        _window.evaluate_js(INJECT_JS)


def main():
    global _window

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    threading.Thread(target=socket_server, daemon=True).start()

    api = Api()
    _window = webview.create_window(
        "Translate Panel",
        BASE_URL,
        js_api=api,
        width=720,
        height=520,
        on_top=True,
        hidden=True,
    )
    _window.events.loaded += on_loaded

    webview.start()

    for path in (PID_FILE, SOCKET_PATH):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
