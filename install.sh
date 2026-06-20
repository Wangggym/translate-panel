#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
DATA="$HOME/.local/share/translate-panel"
VENV="$DATA/venv"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST="$LAUNCH_AGENTS/com.translatepanel.daemon.plist"

echo "→ Installing translate-panel..."

mkdir -p "$BIN" "$DATA" "$LAUNCH_AGENTS"

# Venv + pywebview (one-time; skip if already installed)
if [ ! -f "$VENV/bin/python3" ]; then
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet pywebview "pyobjc>=10.0"
    echo "✓ venv created"
else
    echo "✓ venv exists (skipped)"
fi

# Symlink app files — changes in repo take effect immediately, no reinstall needed
ln -sf "$SCRIPT_DIR/app/daemon.py"  "$DATA/daemon.py"
ln -sf "$SCRIPT_DIR/app/trigger.py" "$DATA/trigger.py"

# Keep PopClip extension's trigger.py in sync with app/trigger.py
cp "$SCRIPT_DIR/app/trigger.py" "$SCRIPT_DIR/popclip/TranslatePanel.popclipext/trigger.py"

# CLI wrapper
cat > "$BIN/translate-panel" << EOF
#!/bin/bash
python3 "$DATA/trigger.py" "\$@"
EOF
chmod +x "$BIN/translate-panel"

# Launch agent (daemon auto-starts at login, launchd restarts on crash)
cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.translatepanel.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV/bin/python3</string>
        <string>$DATA/daemon.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>$DATA/daemon.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✓ symlinks: $DATA/{daemon,trigger}.py → $SCRIPT_DIR/app/"
echo "✓ daemon registered as launch agent"
echo ""
echo "After code changes: just kill the daemon, launchd restarts it automatically."
echo "  pkill -f daemon.py"
echo ""
echo "Install the PopClip extension (one-time):"
echo "  Double-click: $SCRIPT_DIR/popclip/TranslatePanel.popclipext"
