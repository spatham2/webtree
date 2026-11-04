"""Shared core used by both frontends. Owns `tree.json`, pull/review/summary files, and branching."""

import datetime
import pathlib
import shlex
import threading
import uuid

from webtree import branches, codex_cli, config, palettes, store, sun, topics
from webtree import sessions as sessions_mod

SUN = "sun"
LEVELS = ("full", "compacted", "extra_compacted")
SUMMARY_PROMPTS = {
    "compacted": (
        "Summarize this Codex conversation so another session can use it as context. Keep goals, decisions, "
        "file paths, commands, open problems, and current state. Use terse bullets. At most 600 words."
    ),
    "extra_compacted": (
        "Summarize this Codex conversation in at most 120 words: the goal, key decisions, and current state."
    ),
    "brief": "In one sentence of at most 30 words, say what this Codex conversation is about.",
    "purpose": (
        "Write a 5 to 10 word title stating this Codex conversation's purpose and what it has done. "
        "Output only the title, no quotes or trailing period."
    ),
}
TRANSCRIPT_CHAR_LIMIT = 400_000
PURPOSE_CHAR_LIMIT = 100_000
REVIEW_PROMPT = (
    "You are an outside reviewer brought in because the working session may be stuck in its own framing. "
    "Attack the problem below: find flaws, missed alternatives, and wrong assumptions, and propose better "
    "approaches. Be concrete and terse."
)


class CoreError(RuntimeError):
    """A user-facing error from a core operation."""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class Core:
    """All Web Tree operations. Both frontends call only this class."""

    def __init__(self, cfg: config.Config | None = None) -> None:
        self.cfg = cfg or config.Config.from_env()
        self.store = store.TreeStore(self.cfg.tree_path)
        self.index = sessions_mod.SessionIndex(self.cfg.codex_dir)
        self._summary_locks: dict[tuple[str, str], threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ----- reading -----

    def list_sessions(self) -> dict[str, sessions_mod.Session]:
        return self.index.all()

    def session(self, session_id: str) -> sessions_mod.Session:
        found = self.list_sessions().get(session_id)
        if not found:
            raise CoreError(f"unknown session {session_id}")
        return found

    def _node(self, tree: dict, node_id: str) -> dict:
        node = tree["nodes"].get(node_id)
        if not node:
            raise CoreError(f"unknown node {node_id}")
        return node

    def _cluster(self, tree: dict, cluster_id: str) -> dict:
        cluster = tree["clusters"].get(cluster_id)
        if not cluster:
            raise CoreError(f"unknown cluster {cluster_id}")
        return cluster

    def _session_node_id(self, tree: dict, session_id: str) -> str | None:
        return next((nid for nid, n in tree["nodes"].items() if n.get("session_id") == session_id), None)

    def _sun_files(self, project: str, cwd: str) -> list[sun.SunFile]:
        return sun.overall_layer(self.cfg.codex_dir) + sun.project_layer(project, cwd)

    def sun_view(self, project: str | None = None, include_content: bool = False) -> dict:
        """Overall layer plus one section per project (or only `project`)."""
        all_sessions = self.list_sessions()
        cwd_by_project: dict[str, str] = {}
        for s in all_sessions.values():
            if s.cwd:
                cwd_by_project.setdefault(s.project, s.cwd)
        projects = [project] if project else sorted({s.project for s in all_sessions.values()})
        return {
            "overall": [f.to_dict(include_content) for f in sun.overall_layer(self.cfg.codex_dir)],
            "projects": {
                p: [f.to_dict(include_content) for f in sun.project_layer(p, cwd_by_project.get(p, ""))]
                for p in projects
            },
        }

    def session_stats(self, s: sessions_mod.Session) -> dict:
        window = s.context_window or self.cfg.context_window
        pct = 100.0 * s.context_tokens / window if window else 0.0
        tier = palettes.tier_for(pct)
        return {"context_pct": round(pct, 1), "tier": tier["tier"], "tier_name": tier["name"]}

    def view(self) -> dict:
        """Everything a frontend needs to draw the tree, as plain JSON."""
        tree = self.store.load()
        all_sessions = self.list_sessions()
        placed = {n["session_id"] for n in tree["nodes"].values() if n.get("session_id")}
        nodes = {}
        for node_id, node in tree["nodes"].items():
            item = dict(node, id=node_id)
            s = all_sessions.get(node.get("session_id") or "")
            if s:
                item["session"] = s.to_dict()
                item.update(self.session_stats(s))
                current = sun.snapshot_hash(self._sun_files(s.project, s.cwd))
                item["sun_drift"] = bool(node.get("sun_snapshot")) and node["sun_snapshot"] != current
            elif node["kind"] == "planet":
                item["missing"] = True
            tier_name = item.get("tier_name", "mars")
            item["colors"] = palettes.scheme_colors(node.get("palette"), tier_name)
            item["badge"] = tree["signals"].get("jupiter_badge", True) and item.get("tier") == 3
            nodes[node_id] = item
        binned = [
            dict(s.to_dict(), **self.session_stats(s))
            for sid, s in sorted(all_sessions.items(), key=lambda kv: kv[1].created, reverse=True)
            if sid not in placed
        ]
        return {
            "nodes": nodes,
            "clusters": tree["clusters"],
            "pulls": tree["pulls"],
            "reviews": tree["reviews"],
            "signals": tree["signals"],
            "bin": binned,
            "palettes": {"master": palettes.MASTER, "schemes": palettes.SCHEMES, "tiers": palettes.TIERS[:2]},
            "context_window": self.cfg.context_window,
            "mtime": self.store.mtime(),
        }

    # ----- placement -----

    def suggest_parents(self, session_id: str, limit: int = 5) -> list[dict]:
        """Ranked parents for a binned session: same project, related topic, nearest creation time."""
        target = self.session(session_id)
        tree = self.store.load()
        all_sessions = self.list_sessions()
        target_tokens = topics.tokens(target.title)
        target_time = datetime.datetime.fromisoformat(target.created.replace("Z", "+00:00"))
        scored = []
        for node_id, node in tree["nodes"].items():
            s = all_sessions.get(node.get("session_id") or "")
            if not s or node["kind"] != "planet" or s.session_id == session_id:
                continue
            same_project = s.project == target.project
            sim = topics.similarity(target_tokens, topics.tokens(s.title))
            created = datetime.datetime.fromisoformat(s.created.replace("Z", "+00:00"))
            gap_hours = abs((target_time - created).total_seconds()) / 3600
            if created > target_time:
                gap_hours += 10_000
            score = (2.0 if same_project else 0.0) + 3.0 * sim + 1.0 / (1.0 + gap_hours / 24)
            reasons = [r for r, ok in (("same project", same_project), (f"topic {sim:.0%}", sim > 0)) if ok]
            scored.append({"parent": node_id, "title": s.title, "score": round(score, 3), "reasons": reasons})
        scored.sort(key=lambda x: x["score"], reverse=True)
        sun_entry = {"parent": SUN, "title": "Head (top level)", "score": 0.0, "reasons": ["new top-level topic"]}
        return [*scored[: limit - 1], sun_entry]

    def place(self, session_id: str, parent: str) -> str:
        """Place a session under the sun or a planet. Returns the node id."""
        s = self.session(session_id)
        with self.store.transaction() as tree:
            if self._session_node_id(tree, session_id):
                raise CoreError(f"session {session_id} is already placed")
            if parent != SUN and self._node(tree, parent)["kind"] != "planet":
                raise CoreError("parent must be the head or a planet")
            parent_palette = tree["nodes"][parent].get("palette") if parent != SUN else None
            node_id = _new_id("p")
            tree["nodes"][node_id] = {
                "kind": "planet",
                "session_id": session_id,
                "parent": parent,
                "method": "placed",
                "note": "",
                "sun_snapshot": sun.snapshot_hash(self._sun_files(s.project, s.cwd)),
                "project": s.project,
                "cluster": None,
                "palette": parent_palette,
                "created": s.created,
            }
        return node_id

    def move(self, node_id: str, parent: str) -> None:
        with self.store.transaction() as tree:
            node = self._node(tree, node_id)
            ancestor = parent
            while ancestor != SUN:
                if ancestor == node_id:
                    raise CoreError("cannot move a node under its own descendant")
                ancestor = self._node(tree, ancestor)["parent"]
            if node["parent"] != parent:
                self._drop_from_group(tree, node_id)
                node.pop("grouped_from", None)
                parent_group = tree["nodes"][parent].get("group") if parent != SUN else None
                if node.get("group_parent") != parent_group:
                    node.pop("group_parent", None)
            node["parent"] = parent

    def unplace(self, node_id: str) -> None:
        """Return a planet to the drop bin. Its children move up to its parent."""
        with self.store.transaction() as tree:
            node = self._node(tree, node_id)
            self._drop_from_group(tree, node_id)
            for child in tree["nodes"].values():
                if child.get("parent") == node_id:
                    child["parent"] = node["parent"]
                    child.pop("group_parent", None)
            del tree["nodes"][node_id]
            for cluster in tree["clusters"].values():
                if node_id in cluster["members"]:
                    cluster["members"].remove(node_id)

    # ----- clouds -----

    def stage(self, parent: str, method: str = "fork", note: str = "", palette: str | None = None) -> str:
        """Create a cloud under a planet. Nothing runs."""
        if method not in branches.METHODS:
            raise CoreError(f"unknown branch method {method}")
        with self.store.transaction() as tree:
            parent_node = self._node(tree, parent)
            if parent_node["kind"] != "planet":
                raise CoreError("clouds branch from planets")
            node_id = _new_id("c")
            tree["nodes"][node_id] = {
                "kind": "cloud",
                "session_id": None,
                "parent": parent,
                "method": method,
                "note": note,
                "sun_snapshot": "",
                "project": parent_node["project"],
                "cluster": None,
                "palette": palette or parent_node.get("palette"),
                "created": _now(),
            }
        return node_id

    def update_cloud(self, node_id: str, note: str | None = None, palette: str | None = None) -> None:
        with self.store.transaction() as tree:
            node = self._node(tree, node_id)
            if note is not None:
                node["note"] = note
            if palette is not None:
                node["palette"] = palette

    def discard(self, node_id: str) -> None:
        with self.store.transaction() as tree:
            if self._node(tree, node_id)["kind"] != "cloud":
                raise CoreError("only clouds can be discarded")
            self._drop_from_group(tree, node_id)
            del tree["nodes"][node_id]

    # ----- side-by-side groups -----

    def _drop_from_group(self, tree: dict, node_id: str) -> None:
        group = tree["nodes"][node_id].get("group")
        tree["nodes"][node_id]["group"] = None
        if not group:
            return
        rest = [nid for nid, n in tree["nodes"].items() if nid != node_id and n.get("group") == group]
        group_kids = [n for n in tree["nodes"].values() if n.get("group_parent") == group]
        if len(rest) == 1:
            tree["nodes"][rest[0]]["group"] = None
            for kid in group_kids:
                kid.pop("group_parent", None)
            return
        for kid in group_kids:
            if kid["parent"] == node_id:
                kid["parent"] = rest[0]

    def set_group_parent(self, node_id: str, group_id: str | None) -> None:
        """Make a node a child of a whole side-by-side group, or (None) of its individual parent planet."""
        with self.store.transaction() as tree:
            node = self._node(tree, node_id)
            if group_id is None:
                node.pop("group_parent", None)
                return
            members = sorted(
                (nid for nid, n in tree["nodes"].items() if n.get("group") == group_id),
                key=lambda nid: tree["nodes"][nid].get("created") or "",
            )
            if len(members) < 2:
                raise CoreError(f"unknown side-by-side group {group_id}")
            if node_id in members:
                raise CoreError("a group member cannot be a child of its own group")
            if any(self._is_ancestor(tree, node_id, m) for m in members):
                raise CoreError("a node cannot be the child of a group below it")
            if node["parent"] not in members:
                self._drop_from_group(tree, node_id)
                node.pop("grouped_from", None)
                node["parent"] = members[0]
            node["group_parent"] = group_id

    def _is_ancestor(self, tree: dict, maybe_ancestor: str, node_id: str) -> bool:
        current = tree["nodes"][node_id]["parent"]
        while current != SUN:
            if current == maybe_ancestor:
                return True
            current = self._node(tree, current)["parent"]
        return False

    def group_siblings(self, node_ids: list[str]) -> str:
        """Put 2+ nodes side by side on one shared branch. Every node keeps its own descendants.

        They share the first node's parent, unless that parent sits under another member; then they
        share the topmost member's parent so no node ends up under its own descendant.
        """
        if len(set(node_ids)) < 2:
            raise CoreError("a side-by-side group needs at least two nodes")
        with self.store.transaction() as tree:
            members = [self._node(tree, nid) for nid in node_ids]
            ids = set(node_ids)
            target = members[0]["parent"]
            while target != SUN and (target in ids or any(self._is_ancestor(tree, m, target) for m in ids)):
                owner = target if target in ids else next(m for m in ids if self._is_ancestor(tree, m, target))
                target = tree["nodes"][owner]["parent"]
            existing = [m["group"] for m in members if m.get("group")]
            group_id = members[0].get("group") or (existing[0] if existing else _new_id("g"))
            for nid, member in zip(node_ids, members):
                if member["parent"] != target:
                    self._drop_from_group(tree, nid)
                    member.setdefault("grouped_from", member["parent"])
                    member["parent"] = target
                old = member.get("group")
                if old and old != group_id:
                    for node in tree["nodes"].values():
                        if node.get("group") == old:
                            node["group"] = group_id
                        if node.get("group_parent") == old:
                            node["group_parent"] = group_id
                member["group"] = group_id
        return group_id

    def ungroup(self, node_id: str) -> None:
        """Take one node out of its side-by-side group, returning it to where it was grouped from."""
        with self.store.transaction() as tree:
            node = self._node(tree, node_id)
            self._drop_from_group(tree, node_id)
            origin = node.pop("grouped_from", None)
            if origin and (origin == SUN or origin in tree["nodes"]):
                if origin == SUN or not self._is_ancestor(tree, node_id, origin) and origin != node_id:
                    node["parent"] = origin

    def instantiate(self, node_id: str, palette: str | None = None) -> str:
        """Run the cloud's branch method and turn it into a planet. Returns the new session id."""
        tree = self.store.load()
        cloud = self._node(tree, node_id)
        if cloud["kind"] != "cloud":
            raise CoreError("only clouds can be instantiated")
        parent = self.session(self._node(tree, cloud["parent"])["session_id"])
        before = codex_cli.list_sessions(self.cfg.sessions_dir)
        request = branches.BranchRequest(parent.session_id, parent.cwd, cloud.get("note", ""), self.cfg.codex_bin)
        try:
            branches.METHODS[cloud["method"]].start(request)
        except codex_cli.CodexError as exc:
            self._set_cloud_error(node_id, str(exc))
            raise CoreError(str(exc)) from exc
        new = codex_cli.list_sessions(self.cfg.sessions_dir) - before
        if len(new) != 1:
            message = f"expected 1 new session file, found {len(new)}; node left as a cloud"
            self._set_cloud_error(node_id, message)
            raise CoreError(message)
        session_id = new.pop()
        with self.store.transaction() as tree:
            node = self._node(tree, node_id)
            node.update(
                kind="planet",
                session_id=session_id,
                sun_snapshot=sun.snapshot_hash(self._sun_files(parent.project, parent.cwd)),
                created=_now(),
                error=None,
            )
            if palette:
                node["palette"] = palette
        return session_id

    def _set_cloud_error(self, node_id: str, message: str) -> None:
        with self.store.transaction() as tree:
            if node_id in tree["nodes"]:
                tree["nodes"][node_id]["error"] = message

    def split(self, node_id: str, focuses: list[str]) -> list[str]:
        """Stage one fork cloud per focus. The user instantiates each; never automatic."""
        if len(focuses) < 2:
            raise CoreError("split needs at least two focuses")
        return [self.stage(node_id, "fork", f"Split: focus only on {focus}") for focus in focuses]

    def set_palette(self, node_id: str, palette: str) -> None:
        if palette not in palettes.SCHEMES:
            raise CoreError(f"unknown palette {palette}")
        with self.store.transaction() as tree:
            self._node(tree, node_id)["palette"] = palette

    def set_note(self, node_id: str, note: str) -> None:
        with self.store.transaction() as tree:
            self._node(tree, node_id)["note"] = note

    def set_signal(self, name: str, enabled: bool) -> None:
        with self.store.transaction() as tree:
            tree["signals"][name] = enabled

    def open_command(self, node_id: str) -> str:
        tree = self.store.load()
        node = self._node(tree, node_id)
        if not node.get("session_id"):
            raise CoreError("clouds have no session yet")
        s = self.session(node["session_id"])
        return f"cd {shlex.quote(s.cwd or str(pathlib.Path.home()))} && {self.cfg.codex_bin} resume {s.session_id}"

    # ----- clusters -----

    def propose_clusters(self) -> list[dict]:
        """Group planets per project by related topic names; groups of `cluster_min`+ become proposals."""
        tree = self.store.load()
        all_sessions = self.list_sessions()
        clustered = {m for c in tree["clusters"].values() for m in c["members"]}
        by_project: dict[str, list[tuple[str, set[str], str]]] = {}
        for node_id, node in tree["nodes"].items():
            s = all_sessions.get(node.get("session_id") or "")
            if node["kind"] != "planet" or not s or node_id in clustered:
                continue
            by_project.setdefault(s.project, []).append((node_id, topics.tokens(s.title), s.title))
        proposals = []
        for project, items in by_project.items():
            groups: list[list[tuple[str, set[str], str]]] = []
            for item in items:
                best = max(
                    groups,
                    key=lambda g: max(topics.similarity(item[1], other[1]) for other in g),
                    default=None,
                )
                if best and max(topics.similarity(item[1], o[1]) for o in best) >= self.cfg.cluster_similarity:
                    best.append(item)
                else:
                    groups.append([item])
            for group in groups:
                if len(group) >= self.cfg.cluster_min:
                    titles = [t for _, _, t in group]
                    proposals.append(
                        {
                            "project": project,
                            "name": self.heuristic_cluster_name(titles),
                            "members": [g[0] for g in group],
                        }
                    )
        return proposals

    @staticmethod
    def heuristic_cluster_name(titles: list[str]) -> str:
        """A 5-10 word name built from the most common topic words."""
        words = topics.common_words(titles, 8)
        while len(words) < 3:
            words.append(["work", "sessions", "misc"][len(words)])
        return "Sessions about " + ", ".join(words[:-1]) + " and " + words[-1]

    def create_cluster(self, project: str, name: str, members: list[str]) -> str:
        word_count = len(name.split())
        if not 5 <= word_count <= 10:
            raise CoreError(f"cluster names are 5-10 words, got {word_count}")
        with self.store.transaction() as tree:
            for member in members:
                node = self._node(tree, member)
                if node["project"] != project:
                    raise CoreError("clusters live within one project")
                if node.get("cluster"):
                    tree["clusters"][node["cluster"]]["members"].remove(member)
            cluster_id = _new_id("k")
            tree["clusters"][cluster_id] = {"project": project, "name": name, "members": list(members)}
            for member in members:
                tree["nodes"][member]["cluster"] = cluster_id
        return cluster_id

    def accept_proposals(self) -> list[str]:
        return [self.create_cluster(p["project"], p["name"], p["members"]) for p in self.propose_clusters()]

    def rename_cluster(self, cluster_id: str, name: str) -> None:
        if not 5 <= len(name.split()) <= 10:
            raise CoreError("cluster names are 5-10 words")
        with self.store.transaction() as tree:
            self._cluster(tree, cluster_id)["name"] = name

    def move_to_cluster(self, node_id: str, cluster_id: str | None) -> None:
        with self.store.transaction() as tree:
            node = self._node(tree, node_id)
            if node.get("cluster"):
                tree["clusters"][node["cluster"]]["members"].remove(node_id)
            if cluster_id:
                cluster = self._cluster(tree, cluster_id)
                if cluster["project"] != node["project"]:
                    raise CoreError("clusters live within one project")
                cluster["members"].append(node_id)
            node["cluster"] = cluster_id

    def dissolve_cluster(self, cluster_id: str) -> None:
        with self.store.transaction() as tree:
            self._cluster(tree, cluster_id)
            for member in tree["clusters"].pop(cluster_id)["members"]:
                if member in tree["nodes"]:
                    tree["nodes"][member]["cluster"] = None

    def model_cluster_name(self, cluster_id: str) -> str:
        """Ask the summary model for a 5-10 word name from member topic names."""
        tree = self.store.load()
        all_sessions = self.list_sessions()
        members = [
            all_sessions[tree["nodes"][m]["session_id"]]
            for m in self._cluster(tree, cluster_id)["members"]
            if tree["nodes"][m].get("session_id") in all_sessions
        ]
        titles = [s.title for s in members]
        prompt = (
            "Give a name of 5 to 10 words that captures what all these sessions are about. "
            "Reply with only the name.\n\n" + "\n".join(f"- {t}" for t in titles)
        )
        cwd = next((s.cwd for s in members if s.cwd), None)
        reply = self._ask(prompt, "", self.cfg.summary_model, cwd).strip().strip('"')
        words = (reply.splitlines()[0] if reply else "").strip(' ."').split()[:10]
        name = " ".join(words) if len(words) >= 5 else self.heuristic_cluster_name(titles)
        self.rename_cluster(cluster_id, name)
        return name

    # ----- summaries and pulls -----

    def _ask(self, instruction: str, stdin_text: str, model: str, cwd: str | None = None) -> str:
        args = ["exec", "--ephemeral", "--sandbox", "read-only", *(["--model", model] if model else []), instruction]
        try:
            return codex_cli.run(self.cfg.codex_bin, args, cwd, stdin=stdin_text)
        except codex_cli.CodexError as exc:
            hint = " (run `codex login`)" if "login" in str(exc).lower() or "401" in str(exc) else ""
            raise CoreError(f"{exc}{hint}") from exc

    def _summary_path(self, s: sessions_mod.Session, level: str) -> pathlib.Path:
        return self.cfg.summaries_dir / f"{s.session_id}.{level}.{s.file_size}.md"

    def cached_summary(self, session_id: str, level: str) -> str | None:
        """Summary if already generated for the current transcript, else None. Never calls a model."""
        path = self._summary_path(self.session(session_id), level)
        return path.read_text() if path.is_file() else None

    def latest_summary(self, session_id: str, level: str) -> tuple[str | None, bool]:
        """Most recent cached summary, even if the transcript has grown since, and whether it is current."""
        current = self._summary_path(self.session(session_id), level)
        if current.is_file():
            return current.read_text(), True
        older = sorted(self.cfg.summaries_dir.glob(f"{session_id}.{level}.*.md"), key=lambda p: p.stat().st_mtime)
        return (older[-1].read_text(), False) if older else (None, False)

    def summary(self, session_id: str, level: str) -> str:
        """Cached summary of a session's context window at `compacted`, `extra_compacted`, or `brief`."""
        if level not in SUMMARY_PROMPTS:
            raise CoreError(f"level must be one of {tuple(SUMMARY_PROMPTS)}")
        with self._locks_guard:
            lock = self._summary_locks.setdefault((session_id, level), threading.Lock())
        with lock:
            s = self.session(session_id)
            cache = self._summary_path(s, level)
            if cache.is_file():
                return cache.read_text()
            transcript = sessions_mod.render_transcript(s.path)
            if level == "purpose" and len(transcript) > PURPOSE_CHAR_LIMIT:
                half = PURPOSE_CHAR_LIMIT // 2
                transcript = f"{transcript[:half]}\n...\n{transcript[-half:]}"
            text = self._ask(
                SUMMARY_PROMPTS[level], transcript[-TRANSCRIPT_CHAR_LIMIT:], self.cfg.summary_model, s.cwd
            ).strip()
            cache.parent.mkdir(parents=True, exist_ok=True)
            for old in cache.parent.glob(f"{session_id}.{level}.*.md"):
                old.unlink()
            cache.write_text(text)
            return text

    def pull(self, source: str, target: str, level: str = "compacted") -> dict:
        """Write a pull file from a planet or cluster for `target`; return its path and the prompt to paste."""
        tree = self.store.load()
        target_node = self._node(tree, target)
        if target_node["kind"] != "planet":
            raise CoreError("pull target must be a planet")
        if source in tree["clusters"]:
            cluster = tree["clusters"][source]
            level = "cluster_summary"
            sections = [f"# Context pulled from cluster: {cluster['name']}\n"]
            for member in cluster["members"]:
                sid = tree["nodes"][member].get("session_id")
                if sid:
                    sections.append(f"## {self.session(sid).title} (`{sid}`)\n\n{self.summary(sid, 'brief')}\n")
            body = "\n".join(sections)
        else:
            if level not in LEVELS:
                raise CoreError(f"level must be one of {LEVELS}")
            s = self.session(self._node(tree, source)["session_id"])
            content = sessions_mod.render_transcript(s.path) if level == "full" else self.summary(s.session_id, level)
            body = f"# Context pulled from session: {s.title} (`{s.session_id}`, {level})\n\n{content}\n"
        pull_id = _new_id("pull")
        path = self.cfg.pulls_dir / f"{pull_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        with self.store.transaction() as tree:
            tree["pulls"].append(
                {
                    "id": pull_id,
                    "source": source,
                    "target": target,
                    "level": level,
                    "file": str(path),
                    "created": _now(),
                }
            )
        prompt = (
            f"Read the file {path} — context pulled from another session via Web Tree. Use it for the current task."
        )
        return {"id": pull_id, "file": str(path), "prompt": prompt, "chars": len(body)}

    # ----- reviewers -----

    def start_review(self, target: str, problem: str, reviewer: str = "fresh", include: str = "summary") -> str:
        """Record a pending review. `reviewer` is `fresh` or a planet node id. Call run_review to execute."""
        with self.store.transaction() as tree:
            if self._node(tree, target)["kind"] != "planet":
                raise CoreError("reviews target planets")
            if reviewer != "fresh" and self._node(tree, reviewer)["kind"] != "planet":
                raise CoreError("reviewer must be 'fresh' or a planet")
            review_id = _new_id("rev")
            tree["reviews"].append(
                {
                    "id": review_id,
                    "target": target,
                    "reviewer": reviewer,
                    "problem": problem,
                    "include": include,
                    "status": "pending",
                    "file": None,
                    "error": None,
                    "created": _now(),
                }
            )
        return review_id

    def _update_review(self, review_id: str, **fields: object) -> dict:
        with self.store.transaction() as tree:
            review = next((r for r in tree["reviews"] if r["id"] == review_id), None)
            if not review:
                raise CoreError(f"unknown review {review_id}")
            review.update(fields)
            return dict(review)

    def fail_review(self, review_id: str, error: str) -> dict:
        return self._update_review(review_id, status="error", error=error)

    def run_review(self, review_id: str) -> dict:
        """Run a review (blocking). Safe to call from several threads for different reviews."""
        review = self._update_review(review_id, status="running", error=None)
        try:
            tree = self.store.load()
            target = self.session(self._node(tree, review["target"])["session_id"])
            material = f"## Problem\n\n{review['problem']}\n"
            if review["include"] == "summary":
                context = self.summary(target.session_id, "extra_compacted")
                material += f"\n## Brief state of the working session\n\n{context}\n"
            if review["reviewer"] == "fresh":
                text = self._ask(REVIEW_PROMPT, material, self.cfg.reviewer_model, target.cwd)
            else:
                source = self.session(self._node(tree, review["reviewer"])["session_id"])
                args = ["exec", "--ephemeral", "--sandbox", "read-only", "fork", source.session_id]
                text = codex_cli.run(self.cfg.codex_bin, [*args, f"{REVIEW_PROMPT}\n\n{material}"], source.cwd)
        except (codex_cli.CodexError, CoreError, OSError) as exc:
            return self.fail_review(review_id, str(exc))
        path = self.cfg.reviews_dir / f"{review_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Outside review for: {target.title}\n\n{text.strip()}\n")
        return self._update_review(review_id, status="done", file=str(path), completed=_now())

    def review_prompt(self, review_id: str) -> str:
        review = next((r for r in self.store.load()["reviews"] if r["id"] == review_id), None)
        if not review or review["status"] != "done":
            raise CoreError("review is not done")
        return f"An outside reviewer critiqued this problem. Read the file {review['file']} and respond to its points."
