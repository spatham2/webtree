"""Paths and tunables, overridable by environment variables."""

import dataclasses
import os
import pathlib


def _env_path(name: str, default: pathlib.Path) -> pathlib.Path:
    value = os.environ.get(name)
    return pathlib.Path(value).expanduser() if value else default


@dataclasses.dataclass(frozen=True)
class Config:
    """Locations of Codex state and Web Tree's own state."""

    codex_dir: pathlib.Path
    data_dir: pathlib.Path
    codex_bin: str
    context_window: int
    cluster_min: int
    cluster_similarity: float
    summary_model: str
    reviewer_model: str

    @property
    def sessions_dir(self) -> pathlib.Path:
        return self.codex_dir / "sessions"

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
        default_home = _env_path("CODEX_HOME", pathlib.Path.home() / ".codex")
        codex_dir = _env_path("WEBTREE_CODEX_DIR", default_home)
        return cls(
            codex_dir=codex_dir,
            data_dir=_env_path("WEBTREE_HOME", codex_dir / "webtree"),
            codex_bin=os.environ.get("WEBTREE_CODEX_BIN", "codex"),
            context_window=int(os.environ.get("WEBTREE_CONTEXT_WINDOW", "272000")),
            cluster_min=int(os.environ.get("WEBTREE_CLUSTER_MIN", "10")),
            cluster_similarity=float(os.environ.get("WEBTREE_CLUSTER_SIMILARITY", "0.3")),
            summary_model=os.environ.get("WEBTREE_SUMMARY_MODEL", ""),
            reviewer_model=os.environ.get("WEBTREE_REVIEWER_MODEL", ""),
        )
