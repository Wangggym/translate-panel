#!/bin/bash
# trigger.py exits immediately after sending to the daemon socket,
# so PopClip's spinner stops without waiting for the window to close.
~/.local/bin/translate-panel "$POPCLIP_TEXT"
