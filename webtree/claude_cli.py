"""Run the `claude` CLI and detect the session files it creates."""

import pathlib
import subprocess


class ClaudeError(RuntimeError):
    """A `claude` invocation failed or its new session could not be identified."""


def list_transcripts(project_dir: pathlib.Path) -> set[str]:
    return {p.stem for p in project_dir.glob("*.jsonl")} if project_dir.is_dir() else set()


def run(claude_bin: str, args: list[str], cwd: str | None, stdin: str | None = None, timeout: int = 900) -> str:
    """Run claude with args; return stdout or raise ClaudeError."""
    run_cwd = cwd if cwd and pathlib.Path(cwd).is_dir() else None
    try:
        result = subprocess.run(
            [claude_bin, *args], cwd=run_cwd, input=stdin, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaudeError(f"claude failed to run: {exc}") from exc
    if result.returncode != 0:
        raise ClaudeError(f"claude exited {result.returncode}: {(result.stderr or result.stdout).strip()[:500]}")
    return result.stdout


def run_and_find_session(
    claude_bin: str, args: list[str], cwd: str | None, project_dir: pathlib.Path, stdin: str | None = None
) -> tuple[str, str]:
    """Run claude and return (new session id, stdout) found by diffing the project directory."""
    before = list_transcripts(project_dir)
    stdout = run(claude_bin, args, cwd, stdin)
    new = list_transcripts(project_dir) - before
    if len(new) != 1:
        raise ClaudeError(f"expected 1 new session file in {project_dir}, found {len(new)}")
    return new.pop(), stdout
