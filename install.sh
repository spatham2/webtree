#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="${WEBTREE_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$bin_dir"

if [ "${1:-}" = "--docker" ]; then
  docker build -t webtree "$repo"
  cat > "$bin_dir/webtree" <<'SHIM'
#!/usr/bin/env bash
port="${WEBTREE_PORT:-8765}"
flags=(--rm -i --user "$(id -u):$(id -g)" -e HOME="$HOME" -v "$HOME:$HOME" -w "$PWD")
[ -t 0 ] && [ -t 1 ] && flags+=(-t)
for v in $(compgen -e | grep -E '^(WEBTREE_|ANTHROPIC_)'); do flags+=(-e "$v"); done
if [ "${1:-}" = "web" ]; then
  flags+=(-p "127.0.0.1:$port:$port")
  set -- "$@" --host 0.0.0.0 --port "$port"
fi
exec docker run "${flags[@]}" webtree "$@"
SHIM
else
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11+ required (or use ./install.sh --docker)" >&2; exit 1; }
  venv="${WEBTREE_VENV:-$HOME/.local/share/webtree/venv}"
  python3 -m venv "$venv"
  "$venv/bin/pip" install -q --upgrade pip
  "$venv/bin/pip" install -q -e "$repo[test]"
  ln -sf "$venv/bin/webtree" "$bin_dir/webtree"
fi
chmod +x "$bin_dir/webtree"

echo "Installed: $bin_dir/webtree"
case ":$PATH:" in *":$bin_dir:"*) ;; *) echo "Add to PATH: export PATH=\"$bin_dir:\$PATH\"" ;; esac
