#!/usr/bin/env bash
set -euo pipefail

# Absolute project root (where this script lives)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="$ROOT_DIR/bin"
SCRIPTS_DIR="$ROOT_DIR/scripts"

mkdir -p "$BIN_DIR"

for script in "$SCRIPTS_DIR"/*.py; do
  [ -e "$script" ] || continue   # skip if no .py files

  base="$(basename "$script" .py)"
  target="$BIN_DIR/$base"

  cat > "$target" <<EOF
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$ROOT_DIR"
VENV_PY="\$ROOT_DIR/.venv/bin/python3"
MAIN="\$ROOT_DIR/scripts/$base.py"

if [ ! -x "\$VENV_PY" ]; then
  echo "$base: venv Python not found at \$VENV_PY" >&2
  echo "Run 'cd \$ROOT_DIR && make install' first." >&2
  exit 1
fi

if [ ! -f "\$MAIN" ]; then
  echo "$base: script not found at \$MAIN" >&2
  exit 1
fi

exec "\$VENV_PY" "\$MAIN" "\$@"
EOF

  chmod +x "$target"
  echo "Created wrapper: $target"
done
