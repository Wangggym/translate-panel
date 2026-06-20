#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_BIN="$HOME/.local/bin"
DATA_DIR="$HOME/.local/share/translate-panel"
VENV="$DATA_DIR/venv"

echo "→ Setting up translate-panel..."

mkdir -p "$INSTALL_BIN" "$DATA_DIR"

python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet pywebview

cp "$SCRIPT_DIR/app/translate_panel.py" "$DATA_DIR/translate_panel.py"

cat > "$INSTALL_BIN/translate-panel" << EOF
#!/bin/bash
"$VENV/bin/python3" "$DATA_DIR/translate_panel.py" "\$@"
EOF

chmod +x "$INSTALL_BIN/translate-panel"

echo "✓ Installed: $INSTALL_BIN/translate-panel"
echo ""
echo "Next: install the PopClip extension"
echo "  Double-click: $SCRIPT_DIR/popclip/TranslatePanel.popclipext"
echo ""
echo "Make sure $INSTALL_BIN is in your PATH."
