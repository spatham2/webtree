"""Fixtures: a fake ~/.codex tree, two fake git repos, and a fake `codex` binary."""

import json
import os
import pathlib
import stat
import textwrap

import pytest

from webtree import config, core

FAKE_CODEX = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, pathlib, sys, uuid
    args = sys.argv[1:]
    log = os.environ.get("FAKE_CODEX_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps(args) + "\\n")
    if os.environ.get("FAKE_CODEX_FAIL"):
        print("boom", file=sys.stderr); sys.exit(1)
    if "fork" in args and "--ephemeral" not in args:
        parent = args[args.index("fork") + 1]
        sessions = pathlib.Path(os.environ["WEBTREE_CODEX_DIR"]) / "sessions"
        src = next(sessions.rglob(f"rollout-*{parent}.jsonl"))
        new_id = str(uuid.uuid4())
        lines = src.read_text().splitlines()
        meta = json.loads(lines[0])
        meta["payload"].update(id=new_id, forked_from_id=parent)
        (src.parent / f"rollout-2026-10-09T00-00-00-{new_id}.jsonl").write_text(
            "\\n".join([json.dumps(meta), *lines[1:]]) + "\\n"
        )
    if not sys.stdin.isatty():
        sys.stdin.read()
    text = "FAKE OUTPUT " + args[-1][:40]
    if "--output-last-message" in args:
        pathlib.Path(args[args.index("--output-last-message") + 1]).write_text(text)
    print("log noise")
    """
)


def write_session(
    sessions: pathlib.Path,
    cwd: pathlib.Path,
    session_id: str,
    prompt: str,
    created: str = "2026-10-01T00:00:00Z",
    context: int = 1000,
) -> pathlib.Path:
    day = sessions / created[:4] / created[5:7] / created[8:10]
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-{created[:19].replace(':', '-')}-{session_id}.jsonl"

    def line(kind: str, payload: dict) -> dict:
        return {"timestamp": created, "type": kind, "payload": payload}

    usage = {"input_tokens": context - 100, "cached_input_tokens": 0, "output_tokens": 100, "total_tokens": context}
    lines = [
        line(
            "session_meta",
            {"id": session_id, "timestamp": created, "cwd": str(cwd), "git": {"branch": "main"}, "cli_version": "1"},
        ),
        line("turn_context", {"cwd": str(cwd), "model": "gpt-5.5-codex"}),
        line(
            "response_item",
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context/>"}]},
        ),
        line(
            "response_item",
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": f"Please work on {prompt}"}],
            },
        ),
        line(
            "response_item", {"type": "function_call", "name": "shell", "arguments": '{"cmd":["ls"]}', "call_id": "c1"}
        ),
        line(
            "response_item",
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": f"Working on {prompt}."}],
            },
        ),
        line(
            "event_msg",
            {"type": "token_count", "info": {"total_token_usage": usage, "last_token_usage": usage}},
        ),
    ]
    path.write_text("\n".join(json.dumps(item) for item in lines) + "\n")
    return path


def name_session(codex_dir: pathlib.Path, session_id: str, name: str) -> None:
    with (codex_dir / "session_index.jsonl").open("a") as handle:
        handle.write(json.dumps({"id": session_id, "thread_name": name}) + "\n")


@pytest.fixture
def codex_home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    home.mkdir()
    (home / "config.toml").write_text('model = "gpt-5.5-codex"\n')
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    for repo in (repo_a, repo_b):
        (repo / ".git").mkdir(parents=True)
    (repo_a / "AGENTS.md").write_text("SOL means one line.\n")
    write_session(sessions, repo_a, "aaaa0001", "flatsat")
    write_session(sessions, repo_a, "aaaa0002", "battery", created="2026-10-02T00:00:00Z")
    write_session(sessions, repo_b, "bbbb0001", "gui", created="2026-10-03T00:00:00Z", context=200_000)
    name_session(home, "aaaa0001", "Power On Flatsat Integration")
    name_session(home, "aaaa0002", "Flatsat battery emulator")
    name_session(home, "bbbb0001", "Build Webtree GUI")
    fake = tmp_path / "fake_codex"
    fake.write_text(FAKE_CODEX)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("WEBTREE_CODEX_DIR", str(home))
    monkeypatch.setenv("WEBTREE_HOME", str(tmp_path / "webtree_data"))
    monkeypatch.setenv("WEBTREE_CODEX_BIN", str(fake))
    monkeypatch.setenv("WEBTREE_CLUSTER_MIN", "2")
    monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "codex_calls.log"))
    return home


@pytest.fixture
def repo_a(codex_home: pathlib.Path) -> str:
    return str(codex_home.parent / "repo-a")


@pytest.fixture
def repo_b(codex_home: pathlib.Path) -> str:
    return str(codex_home.parent / "repo-b")


@pytest.fixture
def wt(codex_home: pathlib.Path) -> core.Core:
    return core.Core(config.Config.from_env())


def calls(tmp_path: pathlib.Path) -> list[list[str]]:
    log = tmp_path / "codex_calls.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


os.environ.setdefault("WEBTREE_TEST", "1")
