# Web Tree

Constellation GUI and terminal UI for branching Claude Code sessions. Spec: `DESIGN.md`.

## Run

```
cd ~/devel/webtree
python3 -m webtree          # terminal UI
python3 -m webtree web      # web GUI at http://127.0.0.1:8765
python3 -m pytest -q        # tests (fake claude, no real sessions touched)
```

Requires `fastapi`, `uvicorn`, `textual` (`pip install -e .[test]`).

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
