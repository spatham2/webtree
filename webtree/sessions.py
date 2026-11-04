"""Read Codex CLI session rollouts (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`)."""

import dataclasses
import datetime
import json
import pathlib
import threading

from webtree import codex_cli

LAST_MESSAGE_MAX = 4000
TITLE_MAX = 80
SCAFFOLD_PREFIXES = ("<", "# AGENTS.md", "Caveat:")


@dataclasses.dataclass
class Session:
    """Facts about one rollout, derived from its `.jsonl` file."""

    session_id: str
    project: str
    path: pathlib.Path
    title: str
    title_source: str
    first_prompt: str
    cwd: str
    git_branch: str
    model: str
    created: str
    modified: str
    file_size: int
    lifetime_tokens: int
    cache_read_tokens: int
    context_tokens: int
    message_count: int
    last_role: str = ""
    last_message: str = ""
    forked_from: str = ""
    context_window: int = 0

    def to_dict(self) -> dict:
        data = dataclasses.asdict(self)
        data["path"] = str(self.path)
        return data


def project_key(cwd: str) -> str:
    """Project for a cwd: the enclosing git repository root, else the cwd itself."""
    if not cwd:
        return "unknown"
    path = pathlib.Path(cwd)
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return str(candidate)
    return cwd


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") in ("input_text", "output_text", "text")
        )
    return ""


def _is_real_prompt(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith(SCAFFOLD_PREFIXES)


def _iso_from_mtime(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()


def _messages(entry: dict) -> tuple[str, str] | None:
    """(role, text) for a user or assistant chat message line, else None."""
    payload = entry.get("payload") or {}
    if entry.get("type") != "response_item" or payload.get("type") != "message":
        return None
    role = payload.get("role")
    if role not in ("user", "assistant"):
        return None
    text = _text_of(payload.get("content")).strip()
    if not text or (role == "user" and not _is_real_prompt(text)):
        return None
    return role, text


def parse_session(path: pathlib.Path, names: dict[str, str] | None = None) -> Session:
    """Parse one rollout file into a Session."""
    stat = path.stat()
    session_id = cwd = git_branch = model = created = first_prompt = last_role = last_message = forked_from = ""
    lifetime = cache_read = context = messages = window = 0
    with path.open("rb") as handle:
        for raw in handle:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = entry.get("type")
            payload = entry.get("payload") or {}
            if kind == "session_meta":
                if session_id:
                    continue
                session_id = payload.get("id", "")
                cwd = payload.get("cwd", "")
                created = payload.get("timestamp") or entry.get("timestamp", "")
                git_branch = (payload.get("git") or {}).get("branch", "") or ""
                forked_from = payload.get("forked_from_id") or ""
            elif kind == "turn_context":
                model = payload.get("model") or model
                cwd = cwd or payload.get("cwd", "")
            elif kind == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                window = info.get("model_context_window") or window
                total = info.get("total_token_usage") or {}
                last = info.get("last_token_usage") or {}
                if total:
                    lifetime = total.get("total_tokens", 0)
                    cache_read = total.get("cached_input_tokens", 0)
                if last:
                    context = last.get("input_tokens", 0) + last.get("output_tokens", 0)
            else:
                found = _messages(entry)
                if found:
                    last_role, last_message = found
                    if last_role == "user":
                        first_prompt = first_prompt or last_message
                    else:
                        messages += 1
    session_id = session_id or codex_cli.session_id_of(path)
    name = (names or {}).get(session_id, "")
    if name:
        title, source = name, "custom"
    elif first_prompt:
        title, source = first_prompt.splitlines()[0][:TITLE_MAX], "prompt"
    else:
        title, source = session_id[:8], "id"
    return Session(
        session_id=session_id,
        project=project_key(cwd),
        path=path,
        title=title,
        title_source=source,
        first_prompt=first_prompt[:2000],
        cwd=cwd,
        git_branch=git_branch,
        model=model,
        created=created or _iso_from_mtime(stat.st_mtime),
        modified=_iso_from_mtime(stat.st_mtime),
        file_size=stat.st_size,
        lifetime_tokens=lifetime,
        cache_read_tokens=cache_read,
        context_tokens=context,
        message_count=messages,
        last_role=last_role,
        last_message=last_message[:LAST_MESSAGE_MAX],
        forked_from=forked_from,
        context_window=window,
    )


def thread_names(codex_dir: pathlib.Path) -> dict[str, str]:
    """Names given with `/rename`, from `session_index.jsonl` (last entry per thread wins)."""
    names: dict[str, str] = {}
    index = codex_dir / "session_index.jsonl"
    if not index.is_file():
        return names
    for raw in index.read_bytes().splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        thread = entry.get("id") or entry.get("thread_id")
        name = entry.get("thread_name") or entry.get("name")
        if thread and name:
            names[thread] = name
    return names


class SessionIndex:
    """Cached scan of every rollout under the sessions directory."""

    def __init__(self, codex_dir: pathlib.Path) -> None:
        self._codex_dir = codex_dir
        self._sessions_dir = codex_dir / "sessions"
        self._cache: dict[pathlib.Path, tuple[float, int, str, Session]] = {}
        self._lock = threading.Lock()

    def transcript_paths(self) -> list[pathlib.Path]:
        return codex_cli.rollout_paths(self._sessions_dir)

    def stamp_paths(self) -> list[pathlib.Path]:
        return [*self.transcript_paths(), self._codex_dir / "session_index.jsonl"]

    def get(self, path: pathlib.Path, names: dict[str, str] | None = None) -> Session:
        stat = path.stat()
        key = json.dumps(names or {}, sort_keys=True)
        with self._lock:
            cached = self._cache.get(path)
            if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size and cached[2] == key:
                return cached[3]
        session = parse_session(path, names)
        with self._lock:
            self._cache[path] = (stat.st_mtime, stat.st_size, key, session)
        return session

    def all(self) -> dict[str, Session]:
        names = thread_names(self._codex_dir)
        sessions: dict[str, Session] = {}
        for path in self.transcript_paths():
            try:
                session = self.get(path, names)
            except OSError:
                continue
            existing = sessions.get(session.session_id)
            if not existing or session.file_size > existing.file_size:
                sessions[session.session_id] = session
        return sessions


def render_transcript(path: pathlib.Path) -> str:
    """Render a rollout's user and assistant text, plus tool calls, as markdown."""
    parts = []
    with path.open("rb") as handle:
        for raw in handle:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            found = _messages(entry)
            if found:
                role, text = found
                parts.append(f"## {'User' if role == 'user' else 'Assistant'}\n\n{text}\n")
                continue
            payload = entry.get("payload") or {}
            if entry.get("type") == "response_item" and payload.get("type") in ("function_call", "custom_tool_call"):
                args = str(payload.get("arguments") or payload.get("input") or "")[:300]
                parts.append(f"- tool `{payload.get('name')}`: `{args}`\n")
    return "\n".join(parts)
