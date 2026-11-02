# Web Tree

Constellation GUI and terminal UI for branching Claude Code sessions. Spec: `DESIGN.md`.

## Install

```
git clone <repo-url> webtree && cd webtree
./install.sh            # Python 3.11+: private venv in ~/.local/share/webtree, `webtree` in ~/.local/bin
./install.sh --docker   # no local Python needed: builds the `webtree` image and a `webtree` wrapper
```

No venv activation needed afterwards. The Docker wrapper mounts `$HOME` at the same path (so `~/.claude` and session
directories resolve), runs as your user, and forwards `WEBTREE_*` / `ANTHROPIC_*` variables. Set `WEBTREE_PORT` to
change the web port.

## Run

```
webtree                 # terminal UI
webtree web             # web GUI at http://127.0.0.1:8765
```

Tests (native install): `~/.local/share/webtree/venv/bin/python -m pytest -q` (fake claude, no real sessions touched).

## Settings (environment variables)

| Variable | Default |
|---|---|
| `WEBTREE_CLAUDE_DIR` | `~/.claude` |
| `WEBTREE_HOME` (tree.json, pulls, reviews, summaries) | `~/.claude/webtree` |
| `WEBTREE_CLAUDE_BIN` | `claude` |
| `WEBTREE_CONTEXT_WINDOW` | `1000000` |
| `WEBTREE_CLUSTER_MIN` | `10` |
| `WEBTREE_CLUSTER_SIMILARITY` | `0.3` |
| `WEBTREE_SUMMARY_MODEL` | `haiku` |
| `WEBTREE_REVIEWER_MODEL` | `opus` |
| `WEBTREE_CLAUDE_CWD` (directory model calls run from; its `.claude/settings.json` supplies login/gateway) | the session's own cwd |

Instantiate, pull (compacted levels), reviewers, and model cluster naming call the real `claude` CLI and cost tokens.
