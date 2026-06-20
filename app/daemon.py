#!/usr/bin/env python3
"""
translate-panel daemon — pre-warmed local WebKit UI + Google Translate API.

Why local HTML instead of loading translate.google.com:
  Google Translate enforces a strict CSP that blocks pywebview's evaluate_js
  (which uses eval internally). A local HTML file has no CSP, so text injection
  and pywebview.api calls work instantly without any page reload.
"""
import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webview

DATA_DIR = os.path.expanduser("~/.local/share/translate-panel")
SOCKET_PATH = os.path.join(DATA_DIR, "daemon.sock")
PID_FILE = os.path.join(DATA_DIR, "daemon.pid")
HTML_PATH = os.path.join(DATA_DIR, "translate.html")

_window = None
_page_ready = threading.Event()


class Api:
    def translate(self, text: str, sl: str = "auto", tl: str = "zh-CN") -> str:
        url = (
            "https://translate.googleapis.com/translate_a/single"
            f"?client=gtx&sl={sl}&tl={tl}&dt=t"
            f"&q={urllib.parse.quote(text)}"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return "".join(item[0] for item in data[0] if item[0])


def _escape_js(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\n", "\\n")
         .replace("\r", "")
    )


def handle_client(conn):
    try:
        data = b""
        while chunk := conn.recv(4096):
            data += chunk
        text = json.loads(data.decode()).get("text", "")
        _page_ready.wait(timeout=5)
        if _window:
            _window.evaluate_js(f'window.__injectText("{_escape_js(text)}")')
            _window.show()
    except Exception as e:
        print(f"daemon: handle_client: {e}", file=sys.stderr)
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
    _page_ready.set()


def setup_appkit():
    """Runs in a background thread once pywebview's run loop is up."""
    try:
        from AppKit import NSApp, NSNotificationCenter, NSWindowDidResignKeyNotification

        NSApp.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory — no Dock icon

        def on_resign_key(_notification):
            if _window:
                _window.hide()

        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSWindowDidResignKeyNotification,
            None,
            None,
            on_resign_key,
        )
    except Exception as e:
        print(f"daemon: AppKit setup error: {e}", file=sys.stderr)


def main():
    global _window

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    threading.Thread(target=socket_server, daemon=True).start()

    api = Api()
    _window = webview.create_window(
        "Translate Panel",
        f"file://{HTML_PATH}",
        js_api=api,
        width=720,
        height=480,
        on_top=True,
        hidden=True,
    )
    _window.events.loaded += on_loaded

    webview.start(func=setup_appkit)

    for path in (PID_FILE, SOCKET_PATH):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
