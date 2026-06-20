#!/usr/bin/env python3
"""
translate-panel daemon — Google Translate native UI with hash-based text injection.

Why not pywebview.evaluate_js:
  pywebview wraps code in JavaScript eval(), which is blocked by Google Translate's
  Content Security Policy / Trusted Types. Instead we use pyobjc to call
  WKWebView.evaluateJavaScript:completionHandler: directly (no eval wrapper).

Injection flow:
  1. Daemon pre-loads translate.google.com
  2. On first load, we inject a WKUserScript (hashchange listener) via pyobjc's
     WKUserContentController. This persists across subsequent page loads.
  3. We also immediately inject the listener into the already-loaded page via
     native evaluateJavaScript (no pywebview eval wrapper — bypasses CSP/TT).
  4. On each trigger: native evaluateJavaScript sets window.location.hash = '#tp=TEXT'
     → hashchange fires → listener injects text into textarea → GT translates.
  5. Hash change does NOT reload the page.
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
_wkwebview = None          # native WKWebView, set after first load
_page_ready = threading.Event()
_listener_ready = threading.Event()

# Injected via both WKUserScript (future loads) and native evaluateJavaScript
# (current load). Uses no eval() — just property assignment + execCommand.
HASH_LISTENER_JS = """
(function() {
    if (window.__tpListenerAdded) return;
    window.__tpListenerAdded = true;

    function injectFromHash() {
        var hash = window.location.hash;
        if (!hash.startsWith('#tp=')) return;
        var text = decodeURIComponent(hash.slice(4));
        // Clear hash without triggering another hashchange
        history.replaceState(null, '', window.location.pathname + window.location.search);
        var ta = document.querySelector('textarea');
        if (!ta) { setTimeout(injectFromHash.bind(null, text), 150); return; }
        ta.focus();
        ta.select();
        document.execCommand('insertText', false, text);
    }

    window.addEventListener('hashchange', injectFromHash);
    injectFromHash();
})();
"""


# ---------------------------------------------------------------------------
# pyobjc helpers
# ---------------------------------------------------------------------------

def find_wkwebview(view):
    if view is None:
        return None
    # pywebview KVO-wraps WKWebView → class name becomes NSKVONotifying_WebKitHost.
    # Detect by capability (evaluateJavaScript:) rather than exact class name.
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


def native_eval(code: str, on_error=None):
    """Call WKWebView.evaluateJavaScript: directly via pyobjc (no pywebview eval wrapper)."""
    global _wkwebview
    try:
        if not _wkwebview:
            _wkwebview = get_wkwebview()
        if not _wkwebview:
            return

        import objc

        def handler(result, error):
            if error and on_error:
                on_error(str(error))

        _wkwebview.evaluateJavaScript_completionHandler_(code, handler)
    except Exception as e:
        print(f"daemon: native_eval error: {e}", file=sys.stderr)


def setup_hash_listener():
    """Add hash listener to current page (native eval) + WKUserScript for future loads."""
    global _wkwebview

    try:
        _wkwebview = get_wkwebview()
        if not _wkwebview:
            print("daemon: WKWebView not found", file=sys.stderr)
            return

        # 1. Add WKUserScript — runs on every subsequent page load (documentEnd)
        from WebKit import WKUserScript
        script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            HASH_LISTENER_JS,
            1,   # WKUserScriptInjectionTimeAtDocumentEnd
            True,
        )
        _wkwebview.configuration().userContentController().addUserScript_(script)

        # 2. Inject into the already-loaded page via native evaluateJavaScript
        def on_error(err):
            print(f"daemon: listener injection error (CSP?): {err}", file=sys.stderr)
            _listener_ready.set()  # still mark ready; we'll try hash anyway

        def on_success(result, error):
            if error:
                on_error(str(error))
            else:
                print("daemon: hash listener active in current page", file=sys.stderr)
            _listener_ready.set()

        _wkwebview.evaluateJavaScript_completionHandler_(HASH_LISTENER_JS, on_success)

    except Exception as e:
        print(f"daemon: setup_hash_listener error: {e}", file=sys.stderr)
        _listener_ready.set()


# ---------------------------------------------------------------------------
# Text injection
# ---------------------------------------------------------------------------

def inject_text(text: str):
    encoded = urllib.parse.quote(text, safe="")
    native_eval(
        f"window.location.hash = '#tp={encoded}'",
        on_error=lambda e: print(f"daemon: hash inject error: {e}", file=sys.stderr),
    )


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
        _listener_ready.wait(timeout=5)

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
    # Run in background — AppKit calls must be made carefully from non-main threads
    threading.Thread(target=setup_hash_listener, daemon=True).start()


def setup_appkit():
    """Called in background thread after pywebview's run loop starts."""
    try:
        from AppKit import NSApp, NSNotificationCenter, NSWindowDidResignKeyNotification

        NSApp.setActivationPolicy_(1)  # no Dock icon

        def on_resign_key(_notification):
            if _window:
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
