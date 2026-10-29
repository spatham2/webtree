"""Fixtures: a fake ~/.claude tree and a fake `claude` binary."""

import json
import os
import pathlib
import stat
import textwrap

import pytest

from webtree import config, core

FAKE_CLAUDE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, pathlib, sys, uuid
    args = sys.argv[1:]
    log = os.environ.get("FAKE_CLAUDE_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps(args) + "\\n")
    if os.environ.get("FAKE_CLAUDE_FAIL"):
        print("boom", file=sys.stderr); sys.exit(1)
    if "--fork-session" in args and "--no-session-persistence" not in args:
        parent = args[args.index("--resume") + 1]
        projects = pathlib.Path(os.environ["WEBTREE_CLAUDE_DIR"]) / "projects"
        src = next(projects.glob(f"*/{parent}.jsonl"))
        new = src.parent / f"{uuid.uuid4()}.jsonl"
        new.write_text(src.read_text())
    if not sys.stdin.isatty():
        data = sys.stdin.read()
    print("FAKE OUTPUT " + args[-1][:40])
    """
)


def write_session(
    projects: pathlib.Path,
    project: str,
    session_id: str,
    title: str,
    cwd: str = "/tmp",
    created: str = "2026-10-01T00:00:00Z",
    context: int = 1000,
) -> pathlib.Path:
    path = projects / project / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {"type": "custom-title", "customTitle": title, "sessionId": session_id},
        {
            "type": "user",
            "sessionId": session_id,
            "cwd": cwd,
            "gitBranch": "main",
            "timestamp": created,
            "isSidechain": False,
            "message": {"role": "user", "content": f"Please work on {title}"},
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": created,
            "isSidechain": False,
            "message": {
                "id": f"msg-{session_id}",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": f"Working on {title}."}],
                "usage": {
                    "input_tokens": context - 100,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 100,
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


@pytest.fixture
def claude_home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    home = tmp_path / "claude"
    projects = home / "projects"
    (home).mkdir()
    (home / "settings.json").write_text('{"model": "opus"}')
    memory = projects / "-repo-a" / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("- [SOL](feedback_sol.md) — one line\n")
    (memory / "feedback_sol.md").write_text("SOL means one line.\n")
    write_session(projects, "-repo-a", "aaaa0001", "Power On Flatsat Integration")
    write_session(projects, "-repo-a", "aaaa0002", "Flatsat battery emulator", created="2026-10-02T00:00:00Z")
    write_session(projects, "-repo-b", "bbbb0001", "Build Webtree GUI", created="2026-10-03T00:00:00Z", context=700_000)
    fake = tmp_path / "fake_claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("WEBTREE_CLAUDE_DIR", str(home))
    monkeypatch.setenv("WEBTREE_HOME", str(tmp_path / "webtree_data"))
    monkeypatch.setenv("WEBTREE_CLAUDE_BIN", str(fake))
    monkeypatch.setenv("WEBTREE_CLUSTER_MIN", "2")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "claude_calls.log"))
    return home


@pytest.fixture
def wt(claude_home: pathlib.Path) -> core.Core:
    return core.Core(config.Config.from_env())


def calls(tmp_path: pathlib.Path) -> list[list[str]]:
    log = tmp_path / "claude_calls.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


os.environ.setdefault("WEBTREE_TEST", "1")
