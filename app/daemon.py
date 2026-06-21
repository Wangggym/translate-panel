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
_status_item = None    # NSStatusItem — kept alive as module-level ref
_click_handler = None  # ObjC target for status bar click
_hotkey_monitor = None # NSEvent global monitor token

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
    // GT's SPA router may not be ready on cold start; retry every 500ms
    // until the textarea is populated (max 6 attempts = 3 s total).
    var _attempts = 0;
    function _dispatch() {{
        window.dispatchEvent(new PopStateEvent('popstate', {{state: null}}));
        _attempts++;
        if (_attempts < 6) {{
            setTimeout(function() {{
                var ta = document.querySelector('textarea');
                if (!ta || ta.value.trim().length === 0) {{ _dispatch(); }}
            }}, 500);
        }}
    }}
    _dispatch();
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

PAGE_ZOOM = 0.85  # scale factor for Google Translate content

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


def _show_panel():
    """Show the panel and bring it to front."""
    if _window:
        _window.show()
        log.info("_show_panel: panel shown")


# ---------------------------------------------------------------------------
# AppKit setup — status bar icon + global hotkey
# ---------------------------------------------------------------------------

def _install_status_item():
    """Create NSStatusItem on the main thread."""
    global _status_item, _click_handler
    try:
        from Foundation import NSObject
        from AppKit import NSStatusBar, NSVariableStatusItemLength, NSImage

        class _ClickHandler(NSObject):
            def click_(self, sender):
                log.info("status bar clicked: showing panel")
                _show_panel()

        _click_handler = _ClickHandler.alloc().init()
        _status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        btn = _status_item.button()
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "character.bubble", "Show Translate Panel"
        )
        if img is None:
            _status_item.setTitle_("译")
            log.warning("_install_status_item: SF Symbol unavailable, using text label")
        else:
            img.setTemplate_(True)
            btn.setImage_(img)
        btn.setTarget_(_click_handler)
        btn.setAction_("click:")
        log.info("_install_status_item: status bar icon installed")
    except Exception as e:
        log.exception("_install_status_item error: %s", e)


class _StatusItemInstaller(object):
    """Tiny helper to dispatch status item creation to the main thread via PyObjC."""
    pass


def setup_appkit():
    """Called in background thread once pywebview's run loop is up."""
    global _hotkey_monitor
    try:
        from Foundation import NSObject
        from AppKit import (
            NSApp, NSNotificationCenter, NSWindowDidResignKeyNotification,
            NSEvent, NSEventMaskKeyDown,
            NSEventModifierFlagOption, NSEventModifierFlagCommand,
            NSEventModifierFlagControl, NSEventModifierFlagShift,
        )

        NSApp.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory — no Dock icon
        log.info("setup_appkit: Dock icon hidden, registering resign-key observer")

        def on_resign_key(_notification):
            log.info("on_resign_key: window lost focus, pausing audio then hiding")
            if not _window:
                log.warning("on_resign_key: _window is None")
                return
            def do_hide():
                _window.hide()
                log.info("on_resign_key: window hidden")
            pause_audio_then(do_hide)

        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSWindowDidResignKeyNotification, None, None, on_resign_key
        )

        # NSStatusItem must be created on the main thread.
        class _Dispatcher(NSObject):
            def install_(self, _):
                _install_status_item()

        dispatcher = _Dispatcher.alloc().init()
        dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_("install:", None, False)

        # --- Global hotkey: ⌥T (Option+T, no other modifiers) ---
        KEY_T = 17
        MODIFIERS_MASK = (
            NSEventModifierFlagOption | NSEventModifierFlagCommand |
            NSEventModifierFlagControl | NSEventModifierFlagShift
        )

        def on_key(event):
            try:
                if (event.keyCode() == KEY_T and
                        (event.modifierFlags() & MODIFIERS_MASK) == NSEventModifierFlagOption):
                    log.info("hotkey ⌥T: showing panel")
                    _show_panel()
            except Exception as exc:
                log.debug("hotkey handler error: %s", exc)

        # Global monitor requires Accessibility permission.
        # Without it the monitor registers but never fires in other apps.
        import ctypes
        _ax = ctypes.CDLL(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        _ax.AXIsProcessTrusted.restype = ctypes.c_bool
        if _ax.AXIsProcessTrusted():
            log.info("setup_appkit: Accessibility permission granted")
        else:
            log.warning("setup_appkit: Accessibility not granted — opening System Settings")
            from AppKit import NSWorkspace
            from Foundation import NSURL
            NSWorkspace.sharedWorkspace().openURL_(
                NSURL.URLWithString_(
                    "x-apple.systempreferences:com.apple.preference.security"
                    "?Privacy_Accessibility"
                )
            )

        _hotkey_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, on_key
        )
        log.info("setup_appkit: global hotkey ⌥T registered")

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
