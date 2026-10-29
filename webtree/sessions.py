"""Read Claude Code session transcripts."""

import dataclasses
import datetime
import json
import pathlib
import threading

TITLE_MAX = 80


@dataclasses.dataclass
class Session:
    """Facts about one transcript, derived from its `.jsonl` file."""

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

    def to_dict(self) -> dict:
        data = dataclasses.asdict(self)
        data["path"] = str(self.path)
        return data


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _is_real_prompt(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith("<") and not stripped.startswith("Caveat:")


def _iso_from_mtime(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()


def parse_session(path: pathlib.Path) -> Session:
    """Parse one transcript file into a Session."""
    stat = path.stat()
    custom_title = ai_title = first_prompt = cwd = git_branch = model = created = ""
    lifetime = cache_read = context = messages = 0
    seen_message_ids: set[str] = set()
    with path.open("rb") as handle:
        for raw in handle:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = entry.get("type")
            if kind == "custom-title":
                custom_title = entry.get("customTitle") or custom_title
            elif kind == "ai-title":
                ai_title = entry.get("aiTitle") or ai_title
            elif kind in ("user", "assistant"):
                if entry.get("isSidechain"):
                    continue
                created = created or entry.get("timestamp", "")
                cwd = cwd or entry.get("cwd", "")
                git_branch = entry.get("gitBranch", git_branch) or git_branch
                message = entry.get("message") or {}
                if kind == "user":
                    if not first_prompt and not entry.get("isMeta"):
                        text = _text_of(message.get("content"))
                        if _is_real_prompt(text):
                            first_prompt = text.strip()
                    continue
                message_id = message.get("id") or entry.get("uuid", "")
                usage = message.get("usage")
                if not usage or message_id in seen_message_ids:
                    continue
                seen_message_ids.add(message_id)
                messages += 1
                model = message.get("model") or model
                written = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
                read = usage.get("cache_read_input_tokens", 0)
                output = usage.get("output_tokens", 0)
                lifetime += written + output
                cache_read += read
                context = written + read + output
    if custom_title:
        title, source = custom_title, "custom"
    elif ai_title:
        title, source = ai_title, "ai"
    elif first_prompt:
        title, source = first_prompt.splitlines()[0][:TITLE_MAX], "prompt"
    else:
        title, source = path.stem[:8], "id"
    title_file = path.with_suffix("") / "custom-title.json"
    if title_file.is_file():
        try:
            title = json.loads(title_file.read_text()).get("customTitle") or title
            source = "custom"
        except (OSError, json.JSONDecodeError):
            pass
    return Session(
        session_id=path.stem,
        project=path.parent.name,
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
    )


class SessionIndex:
    """Cached scan of every transcript under the projects directory."""

    def __init__(self, projects_dir: pathlib.Path) -> None:
        self._projects_dir = projects_dir
        self._cache: dict[pathlib.Path, tuple[float, int, Session]] = {}
        self._lock = threading.Lock()

    def transcript_paths(self, project: str | None = None) -> list[pathlib.Path]:
        if not self._projects_dir.is_dir():
            return []
        dirs = [self._projects_dir / project] if project else sorted(self._projects_dir.iterdir())
        return [path for d in dirs if d.is_dir() for path in sorted(d.glob("*.jsonl"))]

    def get(self, path: pathlib.Path) -> Session:
        stat = path.stat()
        with self._lock:
            cached = self._cache.get(path)
            if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                return cached[2]
        session = parse_session(path)
        with self._lock:
            self._cache[path] = (stat.st_mtime, stat.st_size, session)
        return session

    def all(self) -> dict[str, Session]:
        sessions = {}
        for path in self.transcript_paths():
            try:
                session = self.get(path)
            except OSError:
                continue
            sessions[session.session_id] = session
        return sessions


def render_transcript(path: pathlib.Path) -> str:
    """Render a transcript's main-thread user and assistant text as markdown."""
    parts = []
    with path.open("rb") as handle:
        for raw in handle:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if entry.get("type") not in ("user", "assistant") or entry.get("isSidechain") or entry.get("isMeta"):
                continue
            message = entry.get("message") or {}
            content = message.get("content")
            if entry["type"] == "user":
                text = _text_of(content)
                if _is_real_prompt(text):
                    parts.append(f"## User\n\n{text.strip()}\n")
                continue
            blocks = content if isinstance(content, list) else []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    parts.append(f"## Assistant\n\n{block['text'].strip()}\n")
                elif block.get("type") == "tool_use":
                    args = json.dumps(block.get("input", {}))[:300]
                    parts.append(f"- tool `{block.get('name')}`: `{args}`\n")
    return "\n".join(parts)
