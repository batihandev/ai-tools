#!/usr/bin/env bash
set -euo pipefail

# Absolute project root (where this script lives)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="$ROOT_DIR/bin"
SCRIPTS_DIR="$ROOT_DIR/scripts"

mkdir -p "$BIN_DIR"

for script in "$SCRIPTS_DIR"/*.py; do
    [ -e "$script" ] || continue

    base="$(basename "$script" .py)"
    target="$BIN_DIR/$base"

    cat > "$target" <<EOF
#!/usr/bin/env bash
set -euo pipefail

# Capture the ACTUAL directory where the user called the command
export USER_PWD=\$(pwd)

ROOT_DIR="$ROOT_DIR"
VENV_PY="\$ROOT_DIR/.venv/bin/python3"

if [ ! -x "\$VENV_PY" ]; then
    echo "$base: venv Python not found at \$VENV_PY" >&2
    exit 1
fi

# Run as module from ROOT_DIR so relative imports work
cd "\$ROOT_DIR"
exec "\$VENV_PY" -m "scripts.$base" "\$@"
EOF

    chmod +x "$target"
    echo "Created wrapper: $target"
done