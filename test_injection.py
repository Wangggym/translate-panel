#!/usr/bin/env python3
"""
Text injection integration test.
Verifies that text sent via the socket appears in GT's URL params and that
GT's Angular app is bootstrapped (textarea exists) so popstate will be handled.

URL params are set synchronously via history.replaceState — reliable signal.
textarea.value is NOT checked: Angular data binding is async and the value
may be empty while a translation fetch is in flight, which is correct behaviour.

Usage:
    python3 test_injection.py
"""
import json
import os
import socket
import sys
import time

SOCK = os.path.expanduser("~/.local/share/translate-panel/daemon.sock")

CHECK_JS = """
(function() {
    var url = new URL(window.location.href);
    var ta = document.querySelector('textarea');
    return JSON.stringify({
        urlText: url.searchParams.get('text'),
        urlOp:   url.searchParams.get('op'),
        urlTl:   url.searchParams.get('tl'),
        textareaExists: !!ta
    });
})();
"""


def send_payload(payload: dict, recv_response=False) -> str | None:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.sendall(json.dumps(payload).encode())
    s.shutdown(socket.SHUT_WR)
    if recv_response:
        data = b""
        while chunk := s.recv(4096):
            data += chunk
        s.close()
        return data.decode()
    s.close()
    return None


def show_text(text: str):
    send_payload({"text": text})


def eval_js(code: str) -> dict:
    raw = send_payload({"action": "eval", "code": code}, recv_response=True)
    return json.loads(raw) if raw else {}


def ok(msg):   print(f"  ✓ {msg}")
def fail(msg): print(f"  ✗ {msg}"); sys.exit(1)


def check_state(label: str, expected_text: str):
    r = eval_js(CHECK_JS)
    if r.get("error"):
        fail(f"JS eval error: {r['error']}")
    state = json.loads(r.get("result") or "{}")
    print(f"   url.text={state.get('urlText')!r}  "
          f"url.op={state.get('urlOp')!r}  "
          f"textarea={'yes' if state.get('textareaExists') else 'NO'}")

    if state.get("urlText") == expected_text:
        ok(f"{label}: URL text param correct")
    else:
        fail(f"{label}: expected {expected_text!r}, got {state.get('urlText')!r}")

    if state.get("urlOp") == "translate":
        ok(f"{label}: URL op=translate")
    else:
        fail(f"{label}: URL op={state.get('urlOp')!r}, expected 'translate'")

    if state.get("textareaExists"):
        ok(f"{label}: textarea exists (Angular bootstrapped)")
    else:
        fail(f"{label}: textarea missing — Angular not ready")


def main():
    print("\n=== translate-panel injection test ===\n")

    # ── Case 1: basic injection ──────────────────────────────────────────────
    TEXT1 = "hello injection test"
    print(f"1. Inject: {TEXT1!r}")
    show_text(TEXT1)
    time.sleep(3)   # allow page load + Angular bootstrap + popstate handling
    check_state("inject-1", TEXT1)

    # ── Case 2: re-injection with different text ─────────────────────────────
    TEXT2 = "good morning world"
    print(f"\n2. Re-inject: {TEXT2!r}")
    show_text(TEXT2)
    time.sleep(2)
    check_state("inject-2", TEXT2)

    # ── Case 3: unicode / CJK text ───────────────────────────────────────────
    TEXT3 = "机器学习与深度神经网络"
    print(f"\n3. Inject CJK: {TEXT3!r}")
    show_text(TEXT3)
    time.sleep(2)
    check_state("inject-cjk", TEXT3)

    # ── Case 4: long text (stress) ───────────────────────────────────────────
    TEXT4 = "The quick brown fox jumps over the lazy dog. " * 5
    print(f"\n4. Inject long text ({len(TEXT4)} chars)")
    show_text(TEXT4)
    time.sleep(2)
    check_state("inject-long", TEXT4)

    print("\n=== All injection tests passed ===\n")


if __name__ == "__main__":
    main()
