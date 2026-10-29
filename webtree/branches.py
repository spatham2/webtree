"""Branch method plugins. v1 ships only `fork`."""

import dataclasses
import pathlib
from typing import Protocol

from webtree import claude_cli

FORK_PROMPT = "This session was forked by Web Tree. Reply with only the word: ready."


@dataclasses.dataclass
class BranchRequest:
    """Inputs a branch method needs to start a child session."""

    parent_session_id: str
    parent_cwd: str
    project_dir: pathlib.Path
    note: str
    claude_bin: str


class BranchMethod(Protocol):
    """Start a new session from a parent. The new id is found by directory diff."""

    name: str

    def start(self, request: BranchRequest) -> None: ...


class ForkMethod:
    """`claude --resume <parent> --fork-session`, run non-interactively once to create the file."""

    name = "fork"

    def start(self, request: BranchRequest) -> None:
        prompt = f"{FORK_PROMPT}\n\nIntent for this branch: {request.note}" if request.note else FORK_PROMPT
        claude_cli.run(
            request.claude_bin,
            ["-p", "--resume", request.parent_session_id, "--fork-session", prompt],
            request.parent_cwd,
        )


METHODS: dict[str, BranchMethod] = {"fork": ForkMethod()}


def register(method: BranchMethod) -> None:
    """Add a branch method. Future methods plug in here without data model changes."""
    METHODS[method.name] = method
