#!/usr/bin/env python3
"""
translate-panel trigger — send selected text to the daemon, starting it if needed.
Called by PopClip; exits immediately after sending so PopClip's spinner stops.
"""
import os
import sys
import json
import socket
import subprocess
import time

DATA_DIR = os.path.expanduser("~/.local/share/translate-panel")
SOCKET_PATH = os.path.join(DATA_DIR, "daemon.sock")
PID_FILE = os.path.join(DATA_DIR, "daemon.pid")
DAEMON_SCRIPT = os.path.join(DATA_DIR, "daemon.py")
VENV_PYTHON = os.path.join(DATA_DIR, "venv/bin/python3")


def daemon_alive() -> bool:
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, OSError):
        return False


def start_daemon():
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    log = open(os.path.join(DATA_DIR, "daemon.log"), "a")
    subprocess.Popen(
        [VENV_PYTHON, DAEMON_SCRIPT],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=log,
    )
    for _ in range(50):
        if os.path.exists(SOCKET_PATH):
            time.sleep(0.1)
            return
        time.sleep(0.2)
    raise RuntimeError("translate-panel daemon did not start in time")


def send(text: str):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(SOCKET_PATH)
        s.sendall(json.dumps({"text": text}).encode())
        s.shutdown(socket.SHUT_WR)


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else ""
    if not daemon_alive():
        start_daemon()
    try:
        send(text)
    except (ConnectionRefusedError, FileNotFoundError):
        # stale socket — restart daemon and retry once
        start_daemon()
        send(text)


if __name__ == "__main__":
    main()
