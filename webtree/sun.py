"""The head: overall and per-project Codex configuration and instructions."""

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


def overall_layer(codex_dir: pathlib.Path) -> list[SunFile]:
    """Files that apply to every session."""
    files = [_read("config", codex_dir / "config.toml"), _read("instructions", codex_dir / "AGENTS.md")]
    override = codex_dir / "AGENTS.override.md"
    if override.is_file():
        files.append(_read("instructions override", override))
    return files


def project_layer(project: str, cwd: str = "") -> list[SunFile]:
    """AGENTS.md files Codex loads for a session: from the project root down to its cwd."""
    root = pathlib.Path(project)
    if not root.is_dir():
        return []
    here = pathlib.Path(cwd) if cwd else root
    chain = [root]
    if here != root and root in here.parents:
        chain += [p for p in reversed(here.parents) if root in p.parents] + [here]
    files = []
    for directory in chain:
        for name in ("AGENTS.override.md", "AGENTS.md"):
            path = directory / name
            if path.is_file():
                files.append(_read("repo instructions", path))
                break
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
