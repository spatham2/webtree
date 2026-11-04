"""Run the `codex` CLI and detect the session files it creates."""

import json
import pathlib
import subprocess
import tempfile


class CodexError(RuntimeError):
    """A `codex` invocation failed or its new session could not be identified."""


def session_id_of(path: pathlib.Path) -> str:
    """Thread id from a rollout's `session_meta` line, else the uuid at the end of its filename."""
    try:
        with path.open("rb") as handle:
            first = json.loads(handle.readline() or b"{}")
        if first.get("type") == "session_meta" and first.get("payload", {}).get("id"):
            return first["payload"]["id"]
    except (OSError, json.JSONDecodeError):
        pass
    return path.stem[-36:]


def rollout_paths(sessions_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(sessions_dir.rglob("rollout-*.jsonl")) if sessions_dir.is_dir() else []


def list_sessions(sessions_dir: pathlib.Path) -> set[str]:
    return {session_id_of(p) for p in rollout_paths(sessions_dir)}


def run(codex_bin: str, args: list[str], cwd: str | None, stdin: str | None = None, timeout: int = 900) -> str:
    """Run codex with args; return the final message (or stdout), or raise CodexError."""
    run_cwd = cwd if cwd and pathlib.Path(cwd).is_dir() else None
    with tempfile.TemporaryDirectory() as tmp:
        last = pathlib.Path(tmp) / "last.md"
        if args and args[0] == "exec":
            args = ["exec", "--skip-git-repo-check", "--color", "never", "--output-last-message", str(last), *args[1:]]
        try:
            result = subprocess.run(
                [codex_bin, *args],
                cwd=run_cwd,
                input=stdin,
                stdin=None if stdin is not None else subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodexError(f"codex failed to run: {exc}") from exc
        if result.returncode != 0:
            raise CodexError(f"codex exited {result.returncode}: {(result.stderr or result.stdout).strip()[-500:]}")
        return last.read_text() if last.is_file() and last.stat().st_size else result.stdout
