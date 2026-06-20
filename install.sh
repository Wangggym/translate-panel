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

# Venv + dependencies
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet pywebview

# Copy app files
cp "$SCRIPT_DIR/app/daemon.py"     "$DATA/daemon.py"
cp "$SCRIPT_DIR/app/trigger.py"    "$DATA/trigger.py"
cp "$SCRIPT_DIR/app/translate.html" "$DATA/translate.html"

# CLI wrapper: `translate-panel "text"`
cat > "$BIN/translate-panel" << EOF
#!/bin/bash
"$VENV/bin/python3" "$DATA/trigger.py" "\$@"
EOF
chmod +x "$BIN/translate-panel"

# Launch agent — keeps daemon alive across reboots
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

echo "✓ translate-panel installed to $BIN/translate-panel"
echo "✓ daemon registered as launch agent (auto-starts at login)"
echo ""
echo "Install the PopClip extension:"
echo "  Double-click: $SCRIPT_DIR/popclip/TranslatePanel.popclipext"
