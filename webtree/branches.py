"""Branch method plugins. v1 ships only `fork`."""

import dataclasses
from typing import Protocol

from webtree import codex_cli

FORK_PROMPT = "This session was forked by Web Tree. Reply with only the word: ready."


@dataclasses.dataclass
class BranchRequest:
    """Inputs a branch method needs to start a child session."""

    parent_session_id: str
    parent_cwd: str
    note: str
    codex_bin: str


class BranchMethod(Protocol):
    """Start a new session from a parent. The new id is found by diffing the sessions directory."""

    name: str

    def start(self, request: BranchRequest) -> None: ...


class ForkMethod:
    """`codex exec fork <parent> <prompt>`, run once non-interactively to create the new rollout."""

    name = "fork"

    def start(self, request: BranchRequest) -> None:
        prompt = f"{FORK_PROMPT}\n\nIntent for this branch: {request.note}" if request.note else FORK_PROMPT
        codex_cli.run(request.codex_bin, ["exec", "fork", request.parent_session_id, prompt], request.parent_cwd)


METHODS: dict[str, BranchMethod] = {"fork": ForkMethod()}


def register(method: BranchMethod) -> None:
    """Add a branch method. Future methods plug in here without data model changes."""
    METHODS[method.name] = method
