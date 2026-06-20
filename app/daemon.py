#!/usr/bin/env python3
"""
translate-panel daemon — Google Translate native UI, text injected via URL params.

Injection strategy:
  pywebview.evaluate_js uses JS eval() → blocked by Google Translate CSP/Trusted Types.
  Instead, pyobjc calls WKWebView.evaluateJavaScript:completionHandler: directly.

  Text is delivered by updating ?text= in the URL via history.replaceState, then
  dispatching a popstate event. This works *with* Google Translate's own SPA router.

Logs: ~/.local/share/translate-panel/daemon.log
"""
import json
import logging
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
# Logging
# ---------------------------------------------------------------------------

os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, "daemon.log")),
        # StreamHandler removed: plist StandardErrorPath already captures stderr
        # to daemon.log, causing every line to appear twice.
    ],
)
log = logging.getLogger("translate-panel")


# NSObject subclass must be at module level (pyobjc forbids re-defining ObjC classes)
from Foundation import NSObject

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
            log.debug("WKWebView found: %s", type(hit).__name__)
            return hit
    log.warning("WKWebView not found in window hierarchy")
    return None


def native_eval(code: str, callback=None):
    """Evaluate JS via native WKWebView API — no pywebview eval() wrapper, bypasses CSP.
    callback(result, error) is optional; errors are always logged."""
    global _wkwebview
    try:
        if not _wkwebview:
            _wkwebview = get_wkwebview()
        if not _wkwebview:
            log.error("native_eval: WKWebView unavailable, skipping: %.80s", code)
            if callback:
                callback(None, "WKWebView not found")
            return

        def on_done(result, error):
            if error:
                log.error("native_eval JS error: %s | code: %.80s", error, code)
            else:
                log.debug("native_eval ok, result=%s | code: %.80s", result, code)
            if callback:
                callback(result, error)

        _wkwebview.evaluateJavaScript_completionHandler_(code, on_done)
    except Exception as e:
        log.exception("native_eval exception: %s", e)
        if callback:
            callback(None, str(e))


# ---------------------------------------------------------------------------
# Text injection: URL params + popstate (works with GT's own SPA router)
# ---------------------------------------------------------------------------

def inject_text(text: str):
    log.info("inject_text: %.60s", text)
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
    return 'ok';
}})();
""")


# ---------------------------------------------------------------------------
# Audio stop: covers <audio>, <video>, speechSynthesis, and iframes
# ---------------------------------------------------------------------------

STOP_AUDIO_JS = """
(function() {
    // Click GT's own "Stop listening" button so GT's state machine stays consistent.
    // This avoids WKWebView's pauseAllMediaPlayback which permanently blocks future playback.
    var btn = Array.from(document.querySelectorAll('button')).find(function(b) {
        var label = (b.getAttribute('aria-label') || '').toLowerCase();
        return label.indexOf('stop') !== -1;
    });
    if (btn) { btn.click(); return 'clicked-stop: ' + btn.getAttribute('aria-label'); }

    // Fallback: pause any DOM audio/video elements directly.
    var n = 0;
    document.querySelectorAll('audio,video').forEach(function(m) {
        m.pause(); m.currentTime = 0; n++;
    });
    return 'paused-dom: ' + n;
})();
"""


def pause_audio_then(callback):
    """Stop GT audio by clicking its own Stop button (keeps GT state machine intact).
    Falls back to pausing DOM audio elements. Does NOT use pauseAllMediaPlayback,
    which permanently blocks future playback until setAllMediaPlaybackSuspended(false)."""
    log.debug("pause_audio_then: running")

    def on_done(result, error):
        if error:
            log.error("pause_audio JS error: %s", error)
        else:
            log.info("pause_audio: %s", result)
        callback()

    native_eval(STOP_AUDIO_JS, callback=on_done)


# ---------------------------------------------------------------------------
# Socket server
# ---------------------------------------------------------------------------

def handle_client(conn):
    try:
        data = b""
        while chunk := conn.recv(4096):
            data += chunk
        payload = json.loads(data.decode())
        action = payload.get("action")

        if action == "eval":
            # Test/debug: evaluate JS and return result synchronously.
            code = payload.get("code", "")
            log.info("handle_client: eval %.80s", code)
            result_holder = [None, None]
            done = threading.Event()

            def on_eval(result, error):
                result_holder[:] = [result, error]
                done.set()

            native_eval(code, callback=on_eval)
            done.wait(timeout=5)
            resp = json.dumps({"result": result_holder[0], "error": result_holder[1]})
            conn.sendall(resp.encode())
            return

        text = payload.get("text", "")
        log.info("handle_client: received text=%.60s", text)

        _page_ready.wait(timeout=10)

        if _window:
            inject_text(text)
            _window.show()
            _make_key_window()  # first click hits content, not just focuses window
            log.info("handle_client: window shown")
        else:
            log.warning("handle_client: _window is None")
    except Exception as e:
        log.exception("handle_client error: %s", e)
    finally:
        conn.close()


def socket_server():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
        srv.bind(SOCKET_PATH)
        srv.listen(5)
        log.info("socket server listening: %s", SOCKET_PATH)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=handle_client, args=(conn,), daemon=True).start()


# ---------------------------------------------------------------------------
# pywebview callbacks
# ---------------------------------------------------------------------------

PAGE_ZOOM = 0.7  # scale factor for Google Translate content

def on_loaded():
    log.info("on_loaded: page ready")
    _page_ready.set()
    threading.Thread(target=_resolve_wkwebview, daemon=True).start()


def _resolve_wkwebview():
    global _wkwebview
    if not _wkwebview:
        _wkwebview = get_wkwebview()
    if _wkwebview:
        try:
            _wkwebview.setPageZoom_(PAGE_ZOOM)
            log.debug("page zoom set to %.2f", PAGE_ZOOM)
        except Exception as e:
            log.debug("setPageZoom_ not available: %s", e)


class _WindowActivator(NSObject):
    """Activates the translate panel on the main thread.

    Timing: PopClip dismisses *after* trigger.py exits and may return focus to the
    source app. We schedule the actual activation 350ms after show() so we grab
    focus after PopClip finishes, not before."""

    def scheduleActivate_(self, _):
        from Foundation import NSTimer
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.35, self, b'activate:', None, False
        )

    def activate_(self, _):
        from AppKit import NSApplication
        app = NSApplication.sharedApplication()
        app.activateIgnoringOtherApps_(True)
        activated = 0
        for win in app.windows():
            if win.isVisible():
                win.makeKeyAndOrderFront_(None)
                activated += 1
        # Log isKeyWindow so we can verify the fix in tests
        key_states = [win.isKeyWindow() for win in app.windows() if win.isVisible()]
        log.info("activate_: done, makeKeyAndOrderFront on %d window(s), isKeyWindow=%s", activated, key_states)

_window_activator = None

def _make_key_window():
    """Schedule delayed activation so it fires after PopClip dismisses."""
    global _window_activator
    if _window_activator is None:
        _window_activator = _WindowActivator.alloc().init()
    # fire-and-forget; actual activation runs 0.35s later on the main thread
    _window_activator.performSelectorOnMainThread_withObject_waitUntilDone_(
        b'scheduleActivate:', None, False
    )


def setup_appkit():
    """Called in background thread once pywebview's run loop is up."""
    try:
        from AppKit import NSApp, NSNotificationCenter, NSWindowDidResignKeyNotification

        NSApp.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory — no Dock icon
        log.info("setup_appkit: Dock icon hidden, registering resign-key observer")

        def on_resign_key(_notification):
            log.info("on_resign_key: window lost focus, pausing audio then hiding")
            if not _window:
                log.warning("on_resign_key: _window is None")
                return
            # Pause audio first; hide only after JS completes so WKWebView is
            # still onscreen when evaluateJavaScript runs.
            def do_hide():
                _window.hide()
                log.info("on_resign_key: window hidden")

            pause_audio_then(do_hide)

        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSWindowDidResignKeyNotification, None, None, on_resign_key
        )
        log.info("setup_appkit: done")
    except Exception as e:
        log.exception("setup_appkit error: %s", e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _window

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    log.info("daemon starting, pid=%d", os.getpid())

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
    log.info("webview window created, starting GUI loop")

    webview.start(func=setup_appkit)

    log.info("daemon exiting")
    for path in (PID_FILE, SOCKET_PATH):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
