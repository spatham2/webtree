"""`tree.json` persistence with a file lock for concurrent frontends."""

import contextlib
import copy
import fcntl
import json
import os
import pathlib
import tempfile
from collections.abc import Iterator

EMPTY_TREE: dict = {
    "nodes": {},
    "clusters": {},
    "pulls": [],
    "reviews": [],
    "signals": {"planet_size": True, "jupiter_badge": True},
}


class TreeStore:
    """Load and atomically save `tree.json` under an exclusive lock."""

    def __init__(self, path: pathlib.Path) -> None:
        self._path = path
        self._lock_path = path.with_suffix(".lock")

    def _read(self) -> dict:
        tree = copy.deepcopy(EMPTY_TREE)
        if self._path.is_file():
            tree.update(json.loads(self._path.read_text()))
            for key, value in EMPTY_TREE["signals"].items():
                tree["signals"].setdefault(key, value)
        return tree

    def load(self) -> dict:
        """Return the current tree (read-only snapshot)."""
        with self._locked():
            return self._read()

    def mtime(self) -> float:
        return self._path.stat().st_mtime if self._path.is_file() else 0.0

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[dict]:
        """Yield the tree for editing; save it on clean exit."""
        with self._locked():
            tree = self._read()
            yield tree
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".tree.", suffix=".json")
            with os.fdopen(fd, "w") as handle:
                json.dump(tree, handle, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
