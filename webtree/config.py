"""Paths and tunables, overridable by environment variables."""

import dataclasses
import os
import pathlib


def _env_path(name: str, default: pathlib.Path) -> pathlib.Path:
    value = os.environ.get(name)
    return pathlib.Path(value).expanduser() if value else default


@dataclasses.dataclass(frozen=True)
class Config:
    """Locations of Claude state and Web Tree's own state."""

    claude_dir: pathlib.Path
    data_dir: pathlib.Path
    claude_bin: str
    context_window: int
    cluster_min: int
    cluster_similarity: float
    summary_model: str
    reviewer_model: str

    @property
    def projects_dir(self) -> pathlib.Path:
        return self.claude_dir / "projects"

    @property
    def tree_path(self) -> pathlib.Path:
        return self.data_dir / "tree.json"

    @property
    def pulls_dir(self) -> pathlib.Path:
        return self.data_dir / "pulls"

    @property
    def reviews_dir(self) -> pathlib.Path:
        return self.data_dir / "reviews"

    @property
    def summaries_dir(self) -> pathlib.Path:
        return self.data_dir / "summaries"

    @classmethod
    def from_env(cls) -> "Config":
        claude_dir = _env_path("WEBTREE_CLAUDE_DIR", pathlib.Path.home() / ".claude")
        return cls(
            claude_dir=claude_dir,
            data_dir=_env_path("WEBTREE_HOME", claude_dir / "webtree"),
            claude_bin=os.environ.get("WEBTREE_CLAUDE_BIN", "claude"),
            context_window=int(os.environ.get("WEBTREE_CONTEXT_WINDOW", "1000000")),
            cluster_min=int(os.environ.get("WEBTREE_CLUSTER_MIN", "10")),
            cluster_similarity=float(os.environ.get("WEBTREE_CLUSTER_SIMILARITY", "0.3")),
            summary_model=os.environ.get("WEBTREE_SUMMARY_MODEL", "haiku"),
            reviewer_model=os.environ.get("WEBTREE_REVIEWER_MODEL", "opus"),
        )
