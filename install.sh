#!/usr/bin/env bash

set -e

REPO_DIR="$(pwd)/fileserver"
SCRIPT_PATH="$REPO_DIR/pythonserver.py"
INSTALL_DIR="$HOME/.local/bin"

git clone https://github.com/NRTLOX/fileserver.git "$REPO_DIR" 2>/dev/null || (cd "$REPO_DIR" && git pull)
cd "$REPO_DIR"

chmod +x pythonserver.py

cat > fileserver << 'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec python3 "pythonserver.py" "${1:-}"
EOF

chmod +x fileserver
mkdir -p "$INSTALL_DIR"
ln -sf "$PWD/fileserver" "$INSTALL_DIR/fileserver"

echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

