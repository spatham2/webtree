# Web Tree

Constellation GUI and terminal UI for branching OpenAI Codex CLI sessions. Spec: `DESIGN.md`.

## Install

```
git clone <repo-url> webtree && cd webtree
./install.sh            # Python 3.11+: private venv in ~/.local/share/webtree, `webtree` in ~/.local/bin
./install.sh --docker   # no local Python needed: builds the `webtree` image and a `webtree` wrapper
```

No venv activation needed afterwards. The Docker wrapper mounts `$HOME` at the same path (so `~/.codex` and session
directories resolve), runs as your user, and forwards `WEBTREE_*` / `CODEX_*` / `OPENAI_*` variables. Set `WEBTREE_PORT` to
change the web port.

## Run

```
webtree                 # terminal UI
webtree web             # web GUI at http://127.0.0.1:8765
```

Tests (native install): `~/.local/share/webtree/venv/bin/python -m pytest -q` (fake codex, no real sessions touched).

## Settings (environment variables)

| Variable | Default |
|---|---|
| `WEBTREE_CODEX_DIR` | `$CODEX_HOME`, else `~/.codex` |
| `WEBTREE_HOME` (tree.json, pulls, reviews, summaries) | `~/.codex/webtree` |
| `WEBTREE_CODEX_BIN` | `codex` |
| `WEBTREE_CONTEXT_WINDOW` (used only when a rollout has no `model_context_window`) | `272000` |
| `WEBTREE_CLUSTER_MIN` | `10` |
| `WEBTREE_CLUSTER_SIMILARITY` | `0.3` |
| `WEBTREE_SUMMARY_MODEL` | Codex default model |
| `WEBTREE_REVIEWER_MODEL` | Codex default model |

## What it reads

- Sessions: `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Titles come from `/rename` names in `session_index.jsonl`,
  else the first prompt. A session's project is the git root of its cwd.
- Head: `~/.codex/config.toml` and `~/.codex/AGENTS.md` (overall), plus each project's `AGENTS.md` chain (project).

Instantiate (`codex exec fork`), pull (compacted levels), reviewers, purpose titles, and model cluster naming call the
real `codex` CLI (`codex exec --ephemeral --sandbox read-only`) and cost tokens. Run `codex login` first.
