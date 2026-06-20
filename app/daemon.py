#!/usr/bin/env python3
"""
translate-panel daemon — Google Translate native UI, text injected via URL params.

Injection strategy:
  pywebview.evaluate_js uses JS eval() → blocked by Google Translate CSP/Trusted Types.
  Instead, pyobjc calls WKWebView.evaluateJavaScript:completionHandler: directly.

  Text is delivered by updating ?text= in the URL via history.replaceState, then
  dispatching a popstate event. This works *with* Google Translate's own SPA router
  (instead of fighting its state management via direct textarea injection, which
  causes the "reverts to previous content" race condition).
"""
import json
import os
import socket
import sys
import threading
import urllib.parse
import webview

DATA_DIR = os.path.expanduser("~/.local/share/translate-panel")
SOCKET_PATH = os.path.join(DATA_DIR, "daemon.sock")
PID_FILE = os.path.join(DATA_DIR, "daemon.pid")
BASE_URL = "https://translate.google.com/?sl=auto&tl=zh-CN&op=translate"

_window = None
_wkwebview = None
_page_ready = threading.Event()


# ---------------------------------------------------------------------------
# pyobjc: find WKWebView
# ---------------------------------------------------------------------------

def find_wkwebview(view):
    """Recurse view hierarchy; detect WKWebView by capability, not class name.
    pywebview KVO-wraps WKWebView → class becomes NSKVONotifying_WebKitHost."""
    if view is None:
        return None
    if hasattr(view, "evaluateJavaScript_completionHandler_"):
        return view
    for sub in (view.subviews() or []):
        hit = find_wkwebview(sub)
        if hit:
            return hit
    return None


def get_wkwebview():
    from AppKit import NSApplication
    for win in NSApplication.sharedApplication().windows():
        hit = find_wkwebview(win.contentView())
        if hit:
            return hit
    return None


def native_eval(code: str):
    """Evaluate JS via native WKWebView API — no pywebview eval() wrapper, bypasses CSP."""
    global _wkwebview
    try:
        if not _wkwebview:
            _wkwebview = get_wkwebview()
        if not _wkwebview:
            print("daemon: WKWebView not found", file=sys.stderr)
            return

        def on_done(result, error):
            if error:
                print(f"daemon: native_eval error: {error}", file=sys.stderr)

        _wkwebview.evaluateJavaScript_completionHandler_(code, on_done)
    except Exception as e:
        print(f"daemon: native_eval exception: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Text injection: URL params + popstate (works with GT's own SPA router)
# ---------------------------------------------------------------------------

def inject_text(text: str):
    # URL-encode the text so embedding in JS string is safe for any input
    encoded = urllib.parse.quote(text, safe="")
    native_eval(f"""
(function() {{
    var text = decodeURIComponent('{encoded}');
    var url = new URL(window.location.href);
    url.searchParams.set('sl', 'auto');
    url.searchParams.set('tl', 'zh-CN');
    url.searchParams.set('text', text);
    url.searchParams.set('op', 'translate');
    history.replaceState(null, '', url.toString());
    window.dispatchEvent(new PopStateEvent('popstate', {{state: null}}));
}})();
""")


# ---------------------------------------------------------------------------
# Socket server
# ---------------------------------------------------------------------------

def handle_client(conn):
    try:
        data = b""
        while chunk := conn.recv(4096):
            data += chunk
        text = json.loads(data.decode()).get("text", "")
        _page_ready.wait(timeout=10)
        if _window:
            inject_text(text)
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


# ---------------------------------------------------------------------------
# pywebview callbacks
# ---------------------------------------------------------------------------

def on_loaded():
    _page_ready.set()
    # Cache the WKWebView reference on first load (runs in pywebview's callback thread)
    threading.Thread(target=lambda: _resolve_wkwebview(), daemon=True).start()


def _resolve_wkwebview():
    global _wkwebview
    if not _wkwebview:
        _wkwebview = get_wkwebview()


def setup_appkit():
    """Called in background thread once pywebview's run loop is up."""
    try:
        from AppKit import NSApp, NSNotificationCenter, NSWindowDidResignKeyNotification

        NSApp.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory — no Dock icon

        def on_resign_key(_notification):
            if _window:
                native_eval("document.querySelectorAll('audio,video').forEach(function(m){m.pause();m.currentTime=0;})")
                _window.hide()

        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSWindowDidResignKeyNotification, None, None, on_resign_key
        )
    except Exception as e:
        print(f"daemon: AppKit setup error: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _window

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    threading.Thread(target=socket_server, daemon=True).start()

    _window = webview.create_window(
        "Translate Panel",
        BASE_URL,
        width=720,
        height=520,
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
