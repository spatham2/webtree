"""The sun: overall and per-project Claude memory."""

import dataclasses
import hashlib
import pathlib


@dataclasses.dataclass
class SunFile:
    """One file shown in the sun."""

    group: str
    path: str
    exists: bool
    size: int
    content: str

    def to_dict(self, include_content: bool = True) -> dict:
        data = dataclasses.asdict(self)
        if not include_content:
            data.pop("content")
        return data


def _read(group: str, path: pathlib.Path) -> SunFile:
    if path.is_file():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            text = ""
        return SunFile(group, str(path), True, path.stat().st_size, text)
    return SunFile(group, str(path), False, 0, "")


def overall_layer(claude_dir: pathlib.Path) -> list[SunFile]:
    """Files that apply to every session."""
    return [_read("config", claude_dir / "settings.json"), _read("instructions", claude_dir / "CLAUDE.md")]


def project_layer(claude_dir: pathlib.Path, project: str, cwd: str = "") -> list[SunFile]:
    """Files that apply to sessions in one project."""
    files = []
    memory_dir = claude_dir / "projects" / project / "memory"
    index = memory_dir / "MEMORY.md"
    if index.is_file():
        files.append(_read("memory index", index))
    if memory_dir.is_dir():
        files.extend(_read("memory", path) for path in sorted(memory_dir.glob("*.md")) if path.name != "MEMORY.md")
    if cwd:
        repo_claude = pathlib.Path(cwd) / "CLAUDE.md"
        if repo_claude.is_file():
            files.append(_read("repo instructions", repo_claude))
    return files


def snapshot_hash(files: list[SunFile]) -> str:
    """Hash of the given sun files' paths and contents."""
    digest = hashlib.sha256()
    for sun_file in sorted(files, key=lambda f: f.path):
        digest.update(sun_file.path.encode())
        digest.update(b"\0")
        digest.update(sun_file.content.encode())
        digest.update(b"\0")
    return digest.hexdigest()[:16]
