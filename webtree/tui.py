"""Terminal frontend: a collapsible tree list, side panel, and drop bin over the shared core."""

import dataclasses
import functools
import os
import shutil
import subprocess
from collections.abc import Callable

from rich import console, table, text
from textual import app, binding, containers, events, screen, widgets, work
from textual.widgets import option_list
from textual.widgets import tree as tree_mod

from webtree import core, palettes

TIER_MARKERS = {1: "●", 2: "◉", 3: "⬤"}
STATUS_STYLES = {"pending": "color(11)", "running": "color(14)", "done": "color(10)", "error": "color(9)"}
LEVEL_LABELS = {"full": "Full transcript", "compacted": "Compacted (default)", "extra_compacted": "Extra-compacted"}
SIGNAL_LABELS = {"planet_size": "Planet size tier markers", "jupiter_badge": "Badge at Jupiter tier"}
Key = tuple[str, str]
SUN_KEY: Key = ("sun", core.SUN)


def human_size(size: int) -> str:
    """Bytes as a short human-readable string."""
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if size >= scale:
            return f"{size / scale:.1f} {unit}"
    return f"{size} B"


def short_time(iso: str) -> str:
    """ISO timestamp trimmed to minutes."""
    return iso[:16].replace("T", " ") if iso else "-"


def ansi_style(hex_color: str) -> str:
    """Rich style for the nearest standard terminal color."""
    return f"color({palettes.ansi_nearest(hex_color)})"


def swatch(scheme_id: str) -> text.Text:
    """Colored blocks for a palette scheme."""
    out = text.Text()
    for index in palettes.SCHEMES[scheme_id]["colors"]:
        out.append("■", style=ansi_style(palettes.MASTER[index]))
    return out


def node_title(item: dict) -> str:
    """Display title for a tree node item."""
    if item.get("session"):
        return item["session"]["title"]
    if item["kind"] == "cloud":
        return item.get("note") or "cloud"
    return item.get("session_id") or item["id"]


def planet_label(item: dict, signals: dict, busy: str | None) -> text.Text:
    """Row label for a planet."""
    label = text.Text()
    color = ansi_style(item["colors"][0]) if item.get("colors") else ""
    if signals.get("planet_size", True):
        label.append(TIER_MARKERS.get(item.get("tier", 1), "●"), style=color)
        label.append(f" {item.get('context_pct', 0):.0f}% ", style="dim")
    else:
        label.append("● ", style=color)
    label.append(node_title(item))
    if item.get("badge"):
        label.append(" [J]", style="bold color(9)")
    if item.get("sun_drift"):
        label.append(" Δhead", style="color(11)")
    if item.get("missing"):
        label.append(" (missing transcript)", style="color(9)")
    if busy:
        label.append(f" ⠿ {busy}", style="color(14)")
    return label


def cloud_label(item: dict, busy: str | None) -> text.Text:
    """Row label for a cloud."""
    label = text.Text("☁ " + (item.get("note") or "cloud"), style="dim italic")
    if item.get("error"):
        label.append(" ✗ error", style="color(9)")
    if busy:
        label.append(f" ⠿ {busy}", style="color(14)")
    return label


def cluster_label(cluster: dict) -> text.Text:
    """Row label for a cluster group."""
    label = text.Text("▣ ", style="bold color(13)")
    label.append(cluster["name"], style="bold")
    label.append(f" ({len(cluster['members'])})", style="dim")
    return label


def review_label(review: dict, reviewer_title: str) -> text.Text:
    """Row label for an outside reviewer."""
    label = text.Text("⌖ reviewer ", style="color(14)")
    label.append(reviewer_title)
    status = review.get("status", "pending")
    label.append(f" [{status}]", style=STATUS_STYLES.get(status, ""))
    return label


def bin_label(entry: dict) -> text.Text:
    """Row label for a binned session."""
    label = text.Text(TIER_MARKERS.get(entry.get("tier", 1), "●"), style="dim")
    label.append(f" {entry.get('context_pct', 0):.0f}% ", style="dim")
    label.append(entry["title"])
    label.append(f"  {short_time(entry['created'])[5:]}", style="dim")
    return label


def group_order(kids: list[str], nodes: dict[str, dict]) -> list[str]:
    """Sort siblings by creation time, keeping each side-by-side group together."""
    ordered = sorted(kids, key=lambda nid: nodes[nid].get("created") or "")
    out: list[str] = []
    for nid in ordered:
        if nid in out:
            continue
        group = nodes[nid].get("group")
        out.extend([m for m in ordered if nodes[m].get("group") == group] if group else [nid])
    return out


def copy_with_system_tool(value: str) -> bool:
    """Copy text using a system clipboard tool; return whether one succeeded."""
    candidates = []
    if os.environ.get("WAYLAND_DISPLAY"):
        candidates.append(["wl-copy"])
    if os.environ.get("DISPLAY"):
        candidates.append(["xclip", "-selection", "clipboard"])
    candidates.append(["pbcopy"])
    for command in candidates:
        if not shutil.which(command[0]):
            continue
        try:
            subprocess.run(
                command,
                input=value,
                text=True,
                timeout=3,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        return True
    return False


@dataclasses.dataclass
class Pending:
    """A two-step action waiting for the user to pick a target row."""

    kind: str
    subject: str
    label: str


class NavList(widgets.OptionList):
    """Option list with vim-style movement."""

    BINDINGS = [
        binding.Binding("j", "cursor_down", "Down", show=False),
        binding.Binding("k", "cursor_up", "Up", show=False),
    ]


class BinList(NavList):
    """The drop bin pane."""

    BINDINGS = [binding.Binding("enter", "select", "Place")]


class WTree(widgets.Tree[Key]):
    """The main tree list."""

    BINDINGS = [
        binding.Binding("enter", "app.open_row", "Open/confirm"),
        binding.Binding("j", "cursor_down", "Down", show=False),
        binding.Binding("k", "cursor_up", "Up", show=False),
    ]

    async def _on_click(self, event: events.Click) -> None:
        await super()._on_click(event)
        if event.chain == 2 and isinstance(self.app, WebTreeApp):
            self.app.copy_resume(self.app.current_key())

    def watch_hover_line(self, previous_hover_line: int, hover_line: int) -> None:
        """Show the hovered row in the side panel."""
        super().watch_hover_line(previous_hover_line, hover_line)
        node = self.get_node_at_line(hover_line) if hover_line >= 0 else self.cursor_node
        if node is not None and node.data is not None and isinstance(self.app, WebTreeApp) and self.app.data:
            self.app.show_details(node.data)


class PaneTab(widgets.Static):
    """A minimized pane; click to restore it."""

    def __init__(self, label: str, pane: str, **kwargs: str) -> None:
        super().__init__(label, **kwargs)
        self.pane = pane

    def on_click(self) -> None:
        if isinstance(self.app, WebTreeApp):
            self.app.restore_pane(self.pane)


class ChoiceModal(screen.ModalScreen[str | None]):
    """Pick one option from a list."""

    BINDINGS = [binding.Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        options: list[tuple[str, text.Text | str]],
        initial: str | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._initial = initial
        self._body = body

    def compose(self) -> app.ComposeResult:
        with containers.Vertical(classes="dialog"):
            yield widgets.Label(self._title, classes="dialog-title")
            if self._body:
                yield widgets.Static(self._body)
            yield NavList(*[option_list.Option(label, id=oid) for oid, label in self._options], id="choices")

    def on_mount(self) -> None:
        choices = self.query_one("#choices", NavList)
        choices.focus()
        ids = [oid for oid, _ in self._options]
        choices.highlighted = ids.index(self._initial) if self._initial in ids else 0

    def on_option_list_option_selected(self, event: widgets.OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option_id)

    def on_option_list_option_highlighted(self, event: widgets.OptionList.OptionHighlighted) -> None:
        event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)


class InputModal(screen.ModalScreen[str | None]):
    """Prompt for one line of text."""

    BINDINGS = [binding.Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, value: str = "", placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._value = value
        self._placeholder = placeholder

    def compose(self) -> app.ComposeResult:
        with containers.Vertical(classes="dialog"):
            yield widgets.Label(self._title, classes="dialog-title")
            yield widgets.Input(value=self._value, placeholder=self._placeholder, id="prompt")
            yield widgets.Label("Enter to accept · Esc to cancel", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#prompt", widgets.Input).focus()

    def on_input_submitted(self, event: widgets.Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextModal(screen.ModalScreen[None]):
    """Show selectable text."""

    BINDINGS = [binding.Binding("escape,q", "close", "Close")]

    def __init__(self, title: str, body: str, hint: str = "") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._hint = hint

    def compose(self) -> app.ComposeResult:
        with containers.Vertical(classes="dialog"):
            yield widgets.Label(self._title, classes="dialog-title")
            yield widgets.TextArea(self._body, read_only=True, soft_wrap=True, id="text")
            yield widgets.Label((self._hint + " · " if self._hint else "") + "Esc/q to close", classes="hint")

    def on_mount(self) -> None:
        self.query_one("#text", widgets.TextArea).focus()

    def action_close(self) -> None:
        self.dismiss(None)


class WebTreeApp(app.App[None]):
    """Web Tree terminal UI."""

    TITLE = "Web Tree"
    CSS = """
    #status { height: 1; background: $boost; padding: 0 1; }
    #main { height: 1fr; }
    #left { width: 3fr; }
    #right { width: 2fr; }
    #filter { display: none; }
    #filter.-visible { display: block; }
    #tree { height: 1fr; border: round $primary; }
    #side-scroll { height: 2fr; border: round $secondary; padding: 0 1; }
    #bin { height: 1fr; border: round $warning; }
    #side-scroll.-hidden, #bin.-hidden, #right.-hidden { display: none; }
    .tab { height: 1; display: none; background: $boost; color: $text-muted; padding: 0 1; }
    .tab:hover { background: $accent; color: $text; }
    .tab.-visible { display: block; }
    #rail { width: 3; display: none; background: $boost; color: $text-muted; content-align: center middle; }
    #rail:hover { background: $accent; color: $text; }
    #rail.-visible { display: block; }
    ModalScreen { align: center middle; }
    .dialog { width: 80%; height: auto; max-height: 85%; border: thick $accent; background: $surface; padding: 1 2; }
    .dialog-title { text-style: bold; margin-bottom: 1; }
    .dialog NavList { height: auto; max-height: 20; }
    .dialog TextArea { height: 16; }
    .hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [
        binding.Binding("slash", "filter", "Filter"),
        binding.Binding("f", "fork", "Fork"),
        binding.Binding("i", "instantiate", "Instantiate"),
        binding.Binding("x", "discard", "Discard"),
        binding.Binding("s", "split", "Split"),
        binding.Binding("p", "pull", "Pull"),
        binding.Binding("r", "review", "Review"),
        binding.Binding("c", "palette", "Palette"),
        binding.Binding("n", "note", "Note"),
        binding.Binding("b", "focus_bin", "Bin"),
        binding.Binding("u", "unplace", "Unplace"),
        binding.Binding("m", "move", "Move"),
        binding.Binding("g", "side_by_side", "Group"),
        binding.Binding("a", "attach", "Attach to group"),
        binding.Binding("K", "clusters", "Clusters"),
        binding.Binding("S", "signals", "Signals"),
        binding.Binding("D", "toggle_details", "Details"),
        binding.Binding("B", "toggle_bin", "Bin pane"),
        binding.Binding("T", "tree_only", "Tree only"),
        binding.Binding("R", "refresh", "Refresh"),
        binding.Binding("escape", "cancel", "Cancel", show=False),
        binding.Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        wt: core.Core | None = None,
        opener: Callable[[str], None] | None = None,
        clipboard: Callable[[str], bool] | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        super().__init__()
        self.wt = wt or core.Core()
        self._opener = opener
        self._clipboard = clipboard or copy_with_system_tool
        self._poll_interval = poll_interval
        self.data: dict = {}
        self._tnodes: dict[Key, tree_mod.TreeNode[Key]] = {}
        self._collapsed: set[Key] = set()
        self._busy: dict[str, str] = {}
        self._reviews_running = 0
        self._filter = ""
        self._pending: Pending | None = None
        self._sun_cache: dict | None = None
        self._open_cache: dict[str, str] = {}
        self._focus_project: str | None = None
        self._stamp: tuple = ()

    def compose(self) -> app.ComposeResult:
        yield widgets.Static(id="status")
        with containers.Horizontal(id="main"):
            with containers.Vertical(id="left"):
                yield widgets.Input(placeholder="filter by title, note, cluster…", id="filter")
                tree = WTree(text.Text("☀ Head"), data=SUN_KEY, id="tree")
                tree.auto_expand = False
                yield tree
            with containers.Vertical(id="right"):
                yield PaneTab("▸ Details", "details", id="details-tab", classes="tab")
                with containers.VerticalScroll(id="side-scroll"):
                    yield widgets.Static(id="side")
                yield PaneTab("▸ Drop bin", "bin", id="bin-tab", classes="tab")
                yield BinList(id="bin")
            yield PaneTab("◂\n\nP\na\nn\ne\ns", "all", id="rail")
        footer = widgets.Footer()
        footer.compact = True
        yield footer

    def on_mount(self) -> None:
        self._update_pane_titles()
        self.reload()
        self.tree.focus()
        self.set_interval(self._poll_interval, self._poll)

    @property
    def tree(self) -> WTree:
        return self.query_one("#tree", WTree)

    @property
    def bin_list(self) -> BinList:
        return self.query_one("#bin", BinList)

    # ----- loading and rendering -----

    def _projects_stamp(self) -> tuple:
        projects = self.wt.cfg.projects_dir
        try:
            entries = [(e.name, e.stat().st_mtime) for e in os.scandir(projects) if e.is_dir()]
            return (projects.stat().st_mtime, tuple(sorted(entries)))
        except OSError:
            return ()

    def _poll(self) -> None:
        stamp = (self.wt.store.mtime(), self._projects_stamp())
        if stamp != self._stamp:
            self.reload()

    def reload(self, select: Key | None = None) -> None:
        """Reload from the core and redraw the tree and bin."""
        self.data = self.wt.view()
        self._stamp = (self.data["mtime"], self._projects_stamp())
        self._sun_cache = None
        self._open_cache = {}
        self._rebuild_tree(select or self.current_key())
        self._rebuild_bin()
        self._update_status()

    def current_key(self) -> Key:
        node = self.tree.cursor_node
        return node.data if node is not None and node.data is not None else SUN_KEY

    def _matches(self, item: dict) -> bool:
        needle = self._filter.casefold()
        hay = " ".join([node_title(item), item.get("note", ""), item.get("session_id") or "", item["id"]])
        return needle in hay.casefold()

    def _rebuild_tree(self, select: Key) -> None:
        tree = self.tree
        nodes = {nid: n for nid, n in self.data["nodes"].items() if n["kind"] in ("planet", "cloud")}
        clusters = self.data["clusters"]
        children: dict[str, list[str]] = {}
        for nid, item in nodes.items():
            parent = item.get("parent") if item.get("parent") in nodes else core.SUN
            children.setdefault(parent, []).append(nid)
        for kids in children.values():
            kids[:] = group_order(kids, nodes)
        cluster_top: dict[str, str] = {}
        for cid, cluster in clusters.items():
            members = set(cluster["members"])
            for member in cluster["members"]:
                if member in nodes and nodes[member].get("parent") not in members:
                    cluster_top[member] = cid
        keep = set(nodes)
        if self._filter:
            keep = set()
            matched = {nid for nid, item in nodes.items() if self._matches(item)}
            for cid, cluster in clusters.items():
                if self._filter.casefold() in cluster["name"].casefold():
                    matched.update(m for m in cluster["members"] if m in nodes)
            for nid in matched:
                while nid in nodes and nid not in keep:
                    keep.add(nid)
                    nid = nodes[nid].get("parent")
        reviews_by_target: dict[str, list[dict]] = {}
        for review in self.data["reviews"]:
            reviews_by_target.setdefault(review["target"], []).append(review)

        tree.clear()
        self._tnodes = {SUN_KEY: tree.root}
        tree.root.set_label(self._sun_label())
        tree.root.data = SUN_KEY
        tree.root.expand()

        def add(parent: tree_mod.TreeNode[Key], nid: str) -> None:
            item = nodes[nid]
            key: Key = ("node", nid)
            kids = [c for c in children.get(nid, []) if c in keep and c not in cluster_top]
            reviews = reviews_by_target.get(nid, [])
            label = (
                planet_label(item, self.data["signals"], self._busy.get(nid))
                if item["kind"] == "planet"
                else cloud_label(item, self._busy.get(nid))
            )
            if item.get("group"):
                label = text.Text("┃ ", style="color(14)") + label
            if kids or reviews:
                tnode = parent.add(label, data=key, expand=key not in self._collapsed)
            else:
                tnode = parent.add_leaf(label, data=key)
            self._tnodes[key] = tnode
            for review in reviews:
                rkey: Key = ("review", review["id"])
                self._tnodes[rkey] = tnode.add_leaf(review_label(review, self._reviewer_title(review)), data=rkey)
            for kid in kids:
                add(tnode, kid)

        for cid, cluster in clusters.items():
            tops = [m for m in cluster["members"] if cluster_top.get(m) == cid and m in keep]
            if not tops:
                continue
            ckey: Key = ("cluster", cid)
            cnode = tree.root.add(cluster_label(cluster), data=ckey, expand=ckey not in self._collapsed)
            self._tnodes[ckey] = cnode
            for member in sorted(tops, key=lambda m: nodes[m].get("created") or ""):
                add(cnode, member)
        for nid in children.get(core.SUN, []):
            if nid in keep and nid not in cluster_top:
                add(tree.root, nid)

        tree.get_node_at_line(0)
        target = self._tnodes.get(select)
        if target is None and select[0] == "node" and select[1] in nodes:
            parent_key: Key = ("node", nodes[select[1]].get("parent") or "")
            target = self._tnodes.get(parent_key)
        tree.move_cursor(target or tree.root)
        self.show_details(target.data if target is not None and target.data else SUN_KEY)

    def _rebuild_bin(self) -> None:
        bin_list = self.bin_list
        previous = None
        if bin_list.highlighted is not None and bin_list.option_count:
            previous = bin_list.get_option_at_index(bin_list.highlighted).id
        entries = self.data["bin"]
        if self._filter:
            needle = self._filter.casefold()
            entries = [e for e in entries if needle in (e["title"] + " " + e["session_id"]).casefold()]
        bin_list.clear_options()
        bin_list.add_options([option_list.Option(bin_label(e), id=e["session_id"]) for e in entries])
        self._bin_title(len(entries))
        ids = [e["session_id"] for e in entries]
        if ids:
            bin_list.highlighted = ids.index(previous) if previous in ids else 0

    def _sun_label(self) -> text.Text:
        label = text.Text("☀ Head", style="bold color(11)")
        planets = sum(1 for n in self.data["nodes"].values() if n["kind"] == "planet")
        label.append(f"  {planets} planets · {len(self.data['bin'])} in bin", style="dim")
        return label

    def _reviewer_title(self, review: dict) -> str:
        if review["reviewer"] == "fresh":
            return "fresh agent"
        item = self.data["nodes"].get(review["reviewer"])
        return node_title(item) if item else review["reviewer"]

    def _title_of(self, ref: str) -> str:
        if ref == core.SUN:
            return "Head"
        if ref in self.data["nodes"]:
            return node_title(self.data["nodes"][ref])
        if ref in self.data["clusters"]:
            return "cluster: " + self.data["clusters"][ref]["name"]
        return ref

    def _update_status(self) -> None:
        nodes = self.data["nodes"].values()
        status = text.Text()
        status.append("Web Tree ", style="bold")
        status.append(
            f"· {sum(n['kind'] == 'planet' for n in nodes)} planets · {sum(n['kind'] == 'cloud' for n in nodes)} "
            f"clouds · bin {len(self.data['bin'])}",
            style="dim",
        )
        if self._filter:
            status.append(f"  filter: {self._filter!r}", style="color(14)")
        busy = list(self._busy.values())
        if busy or self._reviews_running:
            parts = busy + ([f"{self._reviews_running} review(s) running"] if self._reviews_running else [])
            status.append("  ⠿ " + ", ".join(parts), style="bold color(14)")
        if self._pending:
            status.append(f"  ▶ {self._pending.label} · Enter to confirm · Esc to cancel", style="bold color(11)")
        self.query_one("#status", widgets.Static).update(status)

    # ----- side panel -----

    def show_details(self, key: Key) -> None:
        """Render the side panel for a row key."""
        kind, ref = key
        if kind == "sun":
            body = self._sun_details()
        elif kind == "node" and ref in self.data["nodes"]:
            body = self._node_details(self.data["nodes"][ref])
        elif kind == "cluster" and ref in self.data["clusters"]:
            body = self._cluster_details(ref)
        elif kind == "review":
            body = self._review_details(ref)
        elif kind == "bin":
            body = self._bin_details(ref)
        else:
            body = text.Text("")
        self.query_one("#side", widgets.Static).update(body)

    @staticmethod
    def _grid(rows: list[tuple[str, text.Text | str]]) -> table.Table:
        grid = table.Table.grid(padding=(0, 1))
        grid.add_column(style="bold color(12)", no_wrap=True)
        grid.add_column()
        for name, value in rows:
            grid.add_row(name, value)
        return grid

    def _node_details(self, item: dict) -> console.Group:
        nid = item["id"]
        parts: list = [text.Text(node_title(item), style="bold")]
        rows: list[tuple[str, text.Text | str]] = [("Kind", item["kind"])]
        session = item.get("session")
        if session:
            rows += [
                ("Tokens", f"{session['lifetime_tokens']:,} lifetime"),
                ("Transcript", human_size(session["file_size"])),
                ("Context", f"{item.get('context_pct', 0)}%"),
                ("Tier", f"{TIER_MARKERS.get(item.get('tier', 1))} {item.get('tier_name', '')}"),
            ]
        elif item["kind"] == "cloud":
            rows.append(("Transcript", "none yet (cloud)"))
        rows.append(("Parent", self._title_of(item.get("parent") or "")))
        mates = self._group_mates(nid)
        if mates:
            rows.append(("Group", ", ".join(self._title_of(m) for m in mates)))
        if item.get("group_parent"):
            members = [n for n, v in self.data["nodes"].items() if v.get("group") == item["group_parent"]]
            rows.append(("Attached to", "whole group: " + " + ".join(self._title_of(m) for m in members)))
        rows.append(("Created", short_time(item.get("created", ""))))
        if session:
            rows.append(("CWD", session["cwd"] or "-"))
            rows.append(("Branch", session["git_branch"] or "-"))
            rows.append(("Model", session["model"] or "-"))
            rows.append(("Session", session["session_id"]))
        rows.append(("Note", item.get("note") or "-"))
        scheme = item.get("palette")
        palette_text = swatch(scheme) + text.Text(" " + palettes.SCHEMES[scheme]["name"]) if scheme else None
        if palette_text is None:
            palette_text = text.Text()
            for color in item.get("colors", []):
                palette_text.append("■", style=ansi_style(color))
            palette_text.append(" tier default")
        rows.append(("Palette", palette_text))
        if item.get("cluster") and item["cluster"] in self.data["clusters"]:
            rows.append(("Cluster", self.data["clusters"][item["cluster"]]["name"]))
        if item["kind"] == "cloud":
            rows.append(("Method", item.get("method", "fork")))
            if item.get("error"):
                rows.append(("Error", text.Text(item["error"], style="color(9)")))
        if session:
            drift = (
                text.Text("drifted: predates current memory", style="color(11)") if item.get("sun_drift") else "in sync"
            )
            rows.append(("Head", drift))
            rows.append(("Loads", f"overall layer + project {session['project']}"))
            if nid not in self._open_cache:
                ok, command = self._quiet(self.wt.open_command, nid)
                self._open_cache[nid] = command if ok and isinstance(command, str) else ""
            if self._open_cache[nid]:
                rows.append(("Open", self._open_cache[nid]))
        if item.get("missing"):
            rows.append(("Missing", text.Text("transcript not found", style="color(9)")))
        parts.append(self._grid(rows))
        pulls_in = [p for p in self.data["pulls"] if p["target"] == nid]
        pulls_out = [p for p in self.data["pulls"] if p["source"] == nid]
        parts.append(text.Text("\nPulls in", style="bold"))
        parts += [text.Text(f"  ← {self._title_of(p['source'])} ({p['level']})") for p in pulls_in] or [
            text.Text("  none", style="dim")
        ]
        parts.append(text.Text("Pulls out", style="bold"))
        parts += [text.Text(f"  → {self._title_of(p['target'])} ({p['level']})") for p in pulls_out] or [
            text.Text("  none", style="dim")
        ]
        reviews = [r for r in self.data["reviews"] if r["target"] == nid]
        parts.append(text.Text("Reviews", style="bold"))
        for review in reviews:
            line = text.Text(f"  ⌖ {self._reviewer_title(review)} ")
            line.append(f"[{review['status']}]", style=STATUS_STYLES.get(review["status"], ""))
            line.append(f" {review['problem'][:60]}", style="dim")
            parts.append(line)
        if not reviews:
            parts.append(text.Text("  none", style="dim"))
        return console.Group(*parts)

    def _cluster_details(self, cid: str) -> console.Group:
        cluster = self.data["clusters"][cid]
        rows: list[tuple[str, text.Text | str]] = [
            ("Project", cluster["project"]),
            ("Members", str(len(cluster["members"]))),
        ]
        parts: list = [text.Text(cluster["name"], style="bold"), self._grid(rows), text.Text("")]
        parts += [text.Text(f"  • {self._title_of(m)}") for m in cluster["members"]]
        pulls = [p for p in self.data["pulls"] if p["source"] == cid]
        if pulls:
            parts.append(text.Text("Pulls out", style="bold"))
            parts += [text.Text(f"  → {self._title_of(p['target'])} ({p['level']})") for p in pulls]
        return console.Group(*parts)

    def _review_details(self, rid: str) -> console.Group:
        review = next((r for r in self.data["reviews"] if r["id"] == rid), None)
        if review is None:
            return console.Group(text.Text(""))
        status = text.Text(review["status"], style=STATUS_STYLES.get(review["status"], ""))
        rows: list[tuple[str, text.Text | str]] = [
            ("Target", self._title_of(review["target"])),
            ("Reviewer", self._reviewer_title(review)),
            ("Status", status),
            ("Summary", "included" if review.get("include") == "summary" else "not included"),
            ("Created", short_time(review.get("created", ""))),
        ]
        if review.get("file"):
            rows.append(("File", review["file"]))
        if review.get("error"):
            rows.append(("Error", text.Text(review["error"], style="color(9)")))
        hint = "Enter shows the prompt to paste into the session" if review["status"] == "done" else ""
        return console.Group(
            text.Text("Outside reviewer", style="bold"),
            self._grid(rows),
            text.Text("\nProblem", style="bold"),
            text.Text(review["problem"]),
            text.Text("\n" + hint, style="dim"),
        )

    def _bin_details(self, session_id: str) -> console.Group:
        entry = next((e for e in self.data["bin"] if e["session_id"] == session_id), None)
        if entry is None:
            return console.Group(text.Text(""))
        rows: list[tuple[str, text.Text | str]] = [
            ("Project", entry["project"]),
            ("Created", short_time(entry["created"])),
            ("Tokens", f"{entry['lifetime_tokens']:,} lifetime"),
            ("Transcript", human_size(entry["file_size"])),
            ("Context", f"{entry.get('context_pct', 0)}%"),
            ("Tier", entry.get("tier_name", "")),
            ("CWD", entry["cwd"] or "-"),
            ("Branch", entry["git_branch"] or "-"),
            ("Session", session_id),
        ]
        return console.Group(
            text.Text(entry["title"], style="bold"),
            text.Text("binned · Enter to place", style="dim"),
            self._grid(rows),
            text.Text("\nFirst prompt", style="bold"),
            text.Text(entry["first_prompt"][:600] or "-"),
        )

    def _sun_details(self) -> console.Group:
        if self._sun_cache is None:
            self._sun_cache = self.wt.sun_view()
        view = self._sun_cache
        parts: list = [text.Text("☀ Head: what each session loads", style="bold color(11)")]
        parts.append(text.Text("\n▶ Overall layer (every session)", style="bold reverse color(11)"))
        for f in view["overall"]:
            parts.append(self._sun_file_line(f, highlighted=True))
        focus = self._focus_project
        projects = sorted(view["projects"], key=lambda p: (p != focus, p))
        for project in projects:
            highlighted = project == focus
            header = f"\n{'▶ ' if highlighted else ''}Project {project}"
            parts.append(text.Text(header, style="bold reverse color(10)" if highlighted else "bold dim"))
            files = view["projects"][project]
            if not files:
                parts.append(text.Text("  (no memory files)", style="dim"))
            for f in files:
                parts.append(self._sun_file_line(f, highlighted))
        return console.Group(*parts)

    @staticmethod
    def _sun_file_line(f: dict, highlighted: bool) -> text.Text:
        style = "" if highlighted else "dim"
        line = text.Text(f"  {f['group']:<17} ", style="color(12)" if highlighted else "dim")
        line.append(f["path"], style=style)
        line.append(f"  {human_size(f['size'])}" if f["exists"] else "  (absent)", style="dim")
        return line

    # ----- events -----

    def on_tree_node_highlighted(self, event: widgets.Tree.NodeHighlighted) -> None:
        key = event.node.data
        if key is None:
            return
        if key[0] == "node" and key[1] in self.data.get("nodes", {}):
            self._focus_project = self.data["nodes"][key[1]].get("project") or self._focus_project
        self.show_details(key)

    def on_tree_node_collapsed(self, event: widgets.Tree.NodeCollapsed) -> None:
        if event.node.data is not None:
            self._collapsed.add(event.node.data)

    def on_tree_node_expanded(self, event: widgets.Tree.NodeExpanded) -> None:
        if event.node.data is not None:
            self._collapsed.discard(event.node.data)

    def on_option_list_option_highlighted(self, event: widgets.OptionList.OptionHighlighted) -> None:
        if not self.is_running or not self.screen_stack:
            return
        if event.option_list.id == "bin" and event.option_id and self.focused is self.bin_list:
            self.show_details(("bin", event.option_id))

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if event.widget is self.tree and self.data:
            self.show_details(self.current_key())

    def on_option_list_option_selected(self, event: widgets.OptionList.OptionSelected) -> None:
        if event.option_list.id == "bin" and event.option_id:
            self.place_flow(event.option_id)

    def on_input_changed(self, event: widgets.Input.Changed) -> None:
        if event.input.id == "filter":
            self._filter = event.value.strip()
            self._rebuild_tree(self.current_key())
            self._rebuild_bin()
            self._update_status()

    def on_input_submitted(self, event: widgets.Input.Submitted) -> None:
        if event.input.id == "filter":
            if not self._filter:
                event.input.remove_class("-visible")
            self.tree.focus()

    # ----- helpers -----

    @staticmethod
    def _quiet(func: Callable[..., object], *args: object) -> tuple[bool, object]:
        try:
            return True, func(*args)
        except core.CoreError:
            return False, None

    def _try(self, func: Callable[..., object], *args: object) -> tuple[bool, object]:
        try:
            return True, func(*args)
        except core.CoreError as exc:
            self.notify(str(exc), severity="error")
            return False, None

    def _require(self, *kinds: str) -> str | None:
        kind, ref = self.current_key()
        item = self.data["nodes"].get(ref) if kind == "node" else None
        if item is None or item["kind"] not in kinds:
            self.notify(f"Highlight a {' or '.join(kinds)} first", severity="warning")
            return None
        return ref

    def _palette_options(self) -> list[tuple[str, text.Text | str]]:
        return [(sid, swatch(sid) + text.Text(" " + scheme["name"])) for sid, scheme in palettes.SCHEMES.items()]

    def _default_palette(self, item: dict) -> str:
        if item.get("palette"):
            return item["palette"]
        parent = self.data["nodes"].get(item.get("parent") or "")
        if parent and parent.get("palette"):
            return parent["palette"]
        tier_name = (parent or item).get("tier_name", "mars")
        return next(t["default_scheme"] for t in palettes.TIERS if t["name"] == tier_name)

    def _deliver(self, title: str, prompt: str) -> None:
        copied = self._clipboard(prompt)
        if not copied:
            self.copy_to_clipboard(prompt)
        hint = "Copied to clipboard; paste into the session" if copied else "Select and copy the prompt above"
        self.push_screen(TextModal(title, prompt, hint))

    def resume_command(self, key: Key) -> str | None:
        """`claude --resume <id>` for a planet row, else None."""
        kind, ref = key
        session_id = self.data["nodes"].get(ref, {}).get("session_id") if kind == "node" else None
        return f"{self.wt.cfg.claude_bin} --resume {session_id}" if session_id else None

    def copy_resume(self, key: Key) -> None:
        command = self.resume_command(key)
        if not command:
            self.notify("Only planets have a session to resume")
            return
        if not self._clipboard(command):
            self.copy_to_clipboard(command)
        self.notify(f"Copied: {command}")

    def _set_pending(self, pending: Pending | None) -> None:
        self._pending = pending
        self._update_status()
        if pending:
            self.tree.focus()

    # ----- actions -----

    def action_open_row(self) -> None:
        if self._pending:
            self.confirm_pending()
            return
        kind, ref = self.current_key()
        if kind == "cluster":
            self._tnodes[(kind, ref)].toggle()
        elif kind == "review":
            review = next((r for r in self.data["reviews"] if r["id"] == ref), None)
            if review and review["status"] == "done":
                self._deliver("Review result prompt", self.wt.review_prompt(ref))
            elif review and review.get("error"):
                self.push_screen(TextModal("Review error", review["error"]))
            else:
                self.notify("Review is still running")
        elif kind == "node":
            item = self.data["nodes"].get(ref, {})
            if item.get("kind") == "cloud":
                self.notify("Clouds have no session yet; press i to instantiate", severity="warning")
                return
            ok, command = self._try(self.wt.open_command, ref)
            if ok and isinstance(command, str):
                self._open(command)

    def _open(self, command: str) -> None:
        if self._opener:
            self._opener(command)
            return
        if os.environ.get("TMUX"):
            subprocess.Popen(["tmux", "split-window", "-h", command])
            self.notify("Opened in a new tmux pane")
            return
        try:
            with self.suspend():
                subprocess.run(command, shell=True)
        except app.SuspendNotSupported:
            self.push_screen(TextModal("Run this to open the session", command))
        self.reload()

    def action_filter(self) -> None:
        field = self.query_one("#filter", widgets.Input)
        field.add_class("-visible")
        field.focus()

    def action_cancel(self) -> None:
        field = self.query_one("#filter", widgets.Input)
        if self._pending:
            self._set_pending(None)
            self.notify("Cancelled")
        elif self.focused is field or self._filter:
            field.value = ""
            field.remove_class("-visible")
            self.tree.focus()
        elif self.focused is self.bin_list:
            self.tree.focus()

    def action_refresh(self) -> None:
        self.reload()
        self.notify("Refreshed")

    def _update_pane_titles(self) -> None:
        right_hidden = self.query_one("#right").has_class("-hidden")
        arrow = "▸" if not right_hidden else "◂"
        tip = "hide side panes" if not right_hidden else "show side panes"
        self.tree.border_title = f"Tree [@click=app.tree_only]\\[{arrow}][/] [dim]{tip}[/]"
        self.query_one("#side-scroll").border_title = "Details [@click=app.toggle_details]\\[▾][/]"
        self._bin_title()
        self.query_one("#details-tab").set_class(self.query_one("#side-scroll").has_class("-hidden"), "-visible")
        self.query_one("#bin-tab").set_class(self.bin_list.has_class("-hidden"), "-visible")
        self.query_one("#rail").set_class(right_hidden, "-visible")

    def _bin_title(self, count: int | None = None) -> None:
        if count is not None:
            self._bin_count = count
        count = getattr(self, "_bin_count", None)
        suffix = f" · {count}" if count is not None else ""
        self.bin_list.border_title = f"Drop bin (b){suffix} [@click=app.toggle_bin]\\[▾][/]"

    def _set_pane(self, selector: str, visible: bool) -> None:
        self.query_one(selector).set_class(not visible, "-hidden")
        hidden = all(self.query_one(sel).has_class("-hidden") for sel in ("#side-scroll", "#bin"))
        self.query_one("#right").set_class(hidden, "-hidden")
        self._update_pane_titles()
        if not visible and self.focused is not None and not self.focused.display:
            self.tree.focus()

    def restore_pane(self, which: str) -> None:
        if which == "details":
            self._set_pane("#side-scroll", True)
        elif which == "bin":
            self._set_pane("#bin", True)
        else:
            self._set_pane("#side-scroll", True)
            self._set_pane("#bin", True)

    def action_toggle_details(self) -> None:
        self._set_pane("#side-scroll", self.query_one("#side-scroll").has_class("-hidden"))

    def action_toggle_bin(self) -> None:
        self._set_pane("#bin", self.bin_list.has_class("-hidden"))

    def action_tree_only(self) -> None:
        show = self.query_one("#right").has_class("-hidden")
        self._set_pane("#side-scroll", show)
        self._set_pane("#bin", show)
        self.tree.focus()

    def action_focus_bin(self) -> None:
        if self.bin_list.has_class("-hidden"):
            self._set_pane("#bin", True)
        if not self.bin_list.option_count:
            self.notify("Drop bin is empty")
            return
        self.bin_list.focus()
        if self.bin_list.highlighted is not None:
            option = self.bin_list.get_option_at_index(self.bin_list.highlighted)
            if option.id:
                self.show_details(("bin", option.id))

    def action_fork(self) -> None:
        if (nid := self._require("planet")) is not None:
            self.fork_flow(nid)

    @work
    async def fork_flow(self, nid: str) -> None:
        """Stage a fork cloud under a planet."""
        note = await self.push_screen_wait(InputModal("Fork: intent note for the new branch (optional)"))
        if note is None:
            return
        ok, cloud = self._try(self.wt.stage, nid, "fork", note.strip())
        if ok:
            self.reload(("node", cloud))
            self.notify("Cloud staged; press i to instantiate")

    def action_instantiate(self) -> None:
        if (nid := self._require("cloud")) is not None:
            if nid in self._busy:
                self.notify("Already instantiating")
                return
            self.instantiate_flow(nid)

    @work
    async def instantiate_flow(self, nid: str) -> None:
        """Pick a palette and instantiate a cloud in a worker thread."""
        item = self.data["nodes"][nid]
        palette = await self.push_screen_wait(
            ChoiceModal("Instantiate: pick the planet's palette", self._palette_options(), self._default_palette(item))
        )
        if palette is None:
            return
        self._busy[nid] = "instantiating"
        self.reload(("node", nid))
        self.run_worker(functools.partial(self._instantiate_thread, nid, palette), thread=True, group="instantiate")

    def _instantiate_thread(self, nid: str, palette: str) -> None:
        try:
            self.wt.instantiate(nid, palette)
        except core.CoreError as exc:
            self.call_from_thread(self._instantiate_done, nid, str(exc))
        else:
            self.call_from_thread(self._instantiate_done, nid, None)

    def _instantiate_done(self, nid: str, error: str | None) -> None:
        self._busy.pop(nid, None)
        self.reload()
        if error:
            self.notify(f"Instantiate failed: {error}", severity="error", timeout=10)
        else:
            self.notify("Cloud instantiated as a planet")

    def action_discard(self) -> None:
        if (nid := self._require("cloud")) is not None:
            if self._try(self.wt.discard, nid)[0]:
                self.reload()
                self.notify("Cloud discarded")

    def action_split(self) -> None:
        if (nid := self._require("planet")) is not None:
            self.split_flow(nid)

    @work
    async def split_flow(self, nid: str) -> None:
        """Stage one cloud per focus."""
        value = await self.push_screen_wait(
            InputModal("Split: focuses, comma-separated", placeholder="frontend, backend")
        )
        if not value:
            return
        focuses = [f.strip() for f in value.split(",") if f.strip()]
        ok, clouds = self._try(self.wt.split, nid, focuses)
        if ok and isinstance(clouds, list):
            self.reload(("node", clouds[0]))
            self.notify(f"Staged {len(clouds)} clouds")

    def action_palette(self) -> None:
        if (nid := self._require("planet", "cloud")) is not None:
            self.palette_flow(nid)

    @work
    async def palette_flow(self, nid: str) -> None:
        """Change a node's palette."""
        item = self.data["nodes"][nid]
        palette = await self.push_screen_wait(
            ChoiceModal("Palette", self._palette_options(), self._default_palette(item))
        )
        if palette and self._try(self.wt.set_palette, nid, palette)[0]:
            self.reload()

    def action_note(self) -> None:
        if (nid := self._require("planet", "cloud")) is not None:
            self.note_flow(nid)

    @work
    async def note_flow(self, nid: str) -> None:
        """Edit a node's note."""
        note = await self.push_screen_wait(InputModal("Note", self.data["nodes"][nid].get("note", "")))
        if note is not None and self._try(self.wt.set_note, nid, note)[0]:
            self.reload()

    def action_unplace(self) -> None:
        if (nid := self._require("planet")) is not None:
            if self._try(self.wt.unplace, nid)[0]:
                self.reload()
                self.notify("Returned to the drop bin")

    def action_move(self) -> None:
        if (nid := self._require("planet", "cloud")) is not None:
            self._set_pending(Pending("move", nid, f"Move {self._title_of(nid)!r}: pick the new parent"))

    def _group_mates(self, node_id: str) -> list[str]:
        group = self.data["nodes"].get(node_id, {}).get("group")
        if not group:
            return []
        return [nid for nid, n in self.data["nodes"].items() if nid != node_id and n.get("group") == group]

    @work
    async def action_side_by_side(self) -> None:
        """Group the highlighted node with any planet on one shared branch, or separate it."""
        nid = self._require("planet", "cloud")
        if nid is None:
            return
        item = self.data["nodes"][nid]
        siblings = [
            sid
            for sid, n in self.data["nodes"].items()
            if sid != nid
            and n["kind"] in ("planet", "cloud")
            and (not item.get("group") or n.get("group") != item.get("group"))
        ]
        options: list[tuple[str, text.Text | str]] = [(sid, self._title_of(sid)) for sid in siblings]
        if item.get("group"):
            options.insert(0, ("__separate__", "Separate from its group"))
        if not options:
            self.notify("No other planets to group with", severity="warning")
            return
        choice = await self.push_screen_wait(
            ChoiceModal(f"Group with {self._title_of(nid)!r} (it moves next to this one)", options)
        )
        if choice is None:
            return
        if choice == "__separate__":
            ok = self._try(self.wt.ungroup, nid)[0]
        else:
            ok = self._try(self.wt.group_siblings, [nid, choice])[0]
        if ok:
            self.reload(("node", nid))

    def action_attach(self) -> None:
        """Toggle the highlighted node between a child of its planet and a child of that planet's whole group."""
        nid = self._require("planet", "cloud")
        if nid is None:
            return
        item = self.data["nodes"][nid]
        parent_group = self.data["nodes"].get(item.get("parent") or "", {}).get("group")
        if item.get("group_parent"):
            ok = self._try(self.wt.set_group_parent, nid, None)[0]
            message = "Now a child of its planet only"
        elif parent_group:
            ok = self._try(self.wt.set_group_parent, nid, parent_group)[0]
            message = "Now a child of the whole group"
        else:
            self.notify("Its parent is not in a side-by-side group", severity="warning")
            return
        if ok:
            self.reload(("node", nid))
            self.notify(message)

    def action_pull(self) -> None:
        if self._pending and self._pending.kind == "pull":
            self.confirm_pending()
            return
        kind, ref = self.current_key()
        is_planet = kind == "node" and self.data["nodes"].get(ref, {}).get("kind") == "planet"
        if not is_planet and kind != "cluster":
            self.notify("Highlight a planet or cluster as the pull source", severity="warning")
            return
        self._set_pending(Pending("pull", ref, f"Pull from {self._title_of(ref)!r}: pick the target planet, press p"))

    def confirm_pending(self) -> None:
        """Complete the pending two-step action with the highlighted row as target."""
        pending = self._pending
        if pending is None:
            return
        kind, ref = self.current_key()
        target = core.SUN if kind == "sun" else ref
        target_item = self.data["nodes"].get(ref, {}) if kind == "node" else {}
        if pending.kind in ("move", "place"):
            if kind != "sun" and target_item.get("kind") != "planet":
                self.notify("Pick the head or a planet", severity="warning")
                return
            self._set_pending(None)
            if pending.kind == "move":
                if self._try(self.wt.move, pending.subject, target)[0]:
                    self.reload(("node", pending.subject))
            else:
                ok, node_id = self._try(self.wt.place, pending.subject, target)
                if ok and isinstance(node_id, str):
                    self.reload(("node", node_id))
                    self.notify("Placed")
        elif pending.kind == "pull":
            if target_item.get("kind") != "planet" or ref == pending.subject:
                self.notify("Pick a different planet as the pull target", severity="warning")
                return
            self._set_pending(None)
            self.pull_flow(pending.subject, ref)

    @work
    async def pull_flow(self, source: str, target: str) -> None:
        """Confirm the pull, pick a level, and write the pull file in a worker thread."""
        heading = f"Pull {self._title_of(source)!r} into {self._title_of(target)!r}"
        if source in self.data["clusters"]:
            options: list[tuple[str, text.Text | str]] = [("cluster_summary", "Brief summary of each member")]
        else:
            options = [(level, LEVEL_LABELS[level]) for level in core.LEVELS]
        level = await self.push_screen_wait(ChoiceModal(heading, options, "compacted"))
        if level is None:
            return
        self._busy[f"pull:{source}"] = "pulling"
        self._update_status()
        self.run_worker(functools.partial(self._pull_thread, source, target, level), thread=True, group="pull")

    def _pull_thread(self, source: str, target: str, level: str) -> None:
        try:
            result = self.wt.pull(source, target, "compacted" if level == "cluster_summary" else level)
        except core.CoreError as exc:
            self.call_from_thread(self._pull_done, source, None, str(exc))
        else:
            self.call_from_thread(self._pull_done, source, result, None)

    def _pull_done(self, source: str, result: dict | None, error: str | None) -> None:
        self._busy.pop(f"pull:{source}", None)
        self.reload()
        if error or result is None:
            self.notify(f"Pull failed: {error}", severity="error", timeout=10)
            return
        self._deliver(f"Pull ready: {result['file']}", result["prompt"])

    def action_review(self) -> None:
        if (nid := self._require("planet")) is not None:
            self.review_flow(nid)

    @work
    async def review_flow(self, nid: str) -> None:
        """Attach an outside reviewer and run it in a worker thread."""
        others = [
            (oid, "Planet: " + node_title(item))
            for oid, item in self.data["nodes"].items()
            if item["kind"] == "planet" and oid != nid
        ]
        reviewer = await self.push_screen_wait(
            ChoiceModal(f"Reviewer for {self._title_of(nid)!r}", [("fresh", "Fresh agent (new session)"), *others])
        )
        if reviewer is None:
            return
        problem = await self.push_screen_wait(InputModal("Problem for the reviewer to attack"))
        if not problem:
            return
        include = await self.push_screen_wait(
            ChoiceModal("Include a brief summary of this session?", [("summary", "Yes"), ("none", "No")])
        )
        if include is None:
            return
        ok, review_id = self._try(self.wt.start_review, nid, problem, reviewer, include)
        if not ok or not isinstance(review_id, str):
            return
        self._reviews_running += 1
        self.reload(("review", review_id))
        self.run_worker(functools.partial(self._review_thread, review_id), thread=True, group="review")

    def _review_thread(self, review_id: str) -> None:
        try:
            result = self.wt.run_review(review_id)
        except core.CoreError as exc:
            result = {"status": "error", "error": str(exc)}
        self.call_from_thread(self._review_done, result)

    def _review_done(self, result: dict) -> None:
        self._reviews_running = max(0, self._reviews_running - 1)
        self.reload()
        if result.get("status") == "done":
            self.notify("Review done; highlight it and press Enter for the prompt")
        else:
            self.notify(f"Review failed: {result.get('error')}", severity="error", timeout=10)

    @work
    async def place_flow(self, session_id: str) -> None:
        """Show ranked parents for a binned session and place it."""
        ok, suggestions = self._try(self.wt.suggest_parents, session_id)
        if not ok or not isinstance(suggestions, list):
            return
        options: list[tuple[str, text.Text | str]] = []
        for s in suggestions:
            label = text.Text(s["title"])
            label.append(f"  {', '.join(s['reasons'])} · score {s['score']}", style="dim")
            options.append((s["parent"], label))
        options.append(("__pick__", text.Text("Pick any row in the tree…", style="italic")))
        title = self._title_of_bin(session_id)
        parent = await self.push_screen_wait(ChoiceModal(f"Place {title!r} under:", options))
        if parent is None:
            return
        if parent == "__pick__":
            self._set_pending(Pending("place", session_id, f"Place {title!r}: pick the parent row"))
            return
        ok, node_id = self._try(self.wt.place, session_id, parent)
        if ok and isinstance(node_id, str):
            self.reload(("node", node_id))
            self.notify("Placed")

    def _title_of_bin(self, session_id: str) -> str:
        return next((e["title"] for e in self.data["bin"] if e["session_id"] == session_id), session_id)

    def action_signals(self) -> None:
        self.signals_flow()

    @work
    async def signals_flow(self) -> None:
        """Toggle automatic size signals."""
        signals = self.data["signals"]
        names = sorted(set(signals) | set(SIGNAL_LABELS))
        options: list[tuple[str, text.Text | str]] = [
            (name, f"[{'x' if signals.get(name, True) else ' '}] {SIGNAL_LABELS.get(name, name)}") for name in names
        ]
        name = await self.push_screen_wait(ChoiceModal("Signals (select to toggle)", options))
        if name:
            self.wt.set_signal(name, not signals.get(name, True))
            self.reload()

    def _current_cluster(self) -> str | None:
        kind, ref = self.current_key()
        if kind == "cluster":
            return ref
        if kind == "node":
            return self.data["nodes"].get(ref, {}).get("cluster")
        return None

    def action_clusters(self) -> None:
        self.cluster_flow()

    @work
    async def cluster_flow(self) -> None:
        """Cluster menu: propose, accept, rename, model-name, move, dissolve."""
        cid = self._current_cluster()
        kind, ref = self.current_key()
        is_planet = kind == "node" and self.data["nodes"].get(ref, {}).get("kind") == "planet"
        options: list[tuple[str, text.Text | str]] = [
            ("propose", "Propose clusters (review, then accept)"),
            ("accept", "Accept all proposals"),
        ]
        if cid:
            name = self.data["clusters"][cid]["name"]
            options += [
                ("rename", f"Rename {name!r}"),
                ("model", f"Name {name!r} with the model"),
                ("dissolve", f"Dissolve {name!r}"),
            ]
        if is_planet:
            options.append(("move", f"Move {self._title_of(ref)!r} to a cluster"))
        choice = await self.push_screen_wait(ChoiceModal("Clusters", options))
        if choice == "propose":
            proposals = self.wt.propose_clusters()
            if not proposals:
                self.notify("No cluster proposals")
                return
            body = "\n\n".join(
                f"{p['name']}  [{p['project']}]\n" + "\n".join(f"  • {self._title_of(m)}" for m in p["members"])
                for p in proposals
            )
            accept = await self.push_screen_wait(
                ChoiceModal("Accept these proposals?", [("yes", "Accept all"), ("no", "Not now")], body=body)
            )
            if accept == "yes":
                self._accept_clusters()
        elif choice == "accept":
            self._accept_clusters()
        elif choice == "rename" and cid:
            name = await self.push_screen_wait(
                InputModal("Cluster name (5-10 words)", self.data["clusters"][cid]["name"])
            )
            if name and self._try(self.wt.rename_cluster, cid, name.strip())[0]:
                self.reload()
        elif choice == "model" and cid:
            self._busy[f"cluster:{cid}"] = "naming cluster"
            self._update_status()
            self.run_worker(functools.partial(self._model_name_thread, cid), thread=True, group="cluster")
        elif choice == "dissolve" and cid:
            self.wt.dissolve_cluster(cid)
            self.reload()
        elif choice == "move" and is_planet:
            project = self.data["nodes"][ref]["project"]
            targets: list[tuple[str, text.Text | str]] = [
                (k, c["name"]) for k, c in self.data["clusters"].items() if c["project"] == project
            ]
            target = await self.push_screen_wait(ChoiceModal("Move to cluster", [*targets, ("__none__", "No cluster")]))
            if target and self._try(self.wt.move_to_cluster, ref, None if target == "__none__" else target)[0]:
                self.reload(("node", ref))

    def _accept_clusters(self) -> None:
        ok, created = self._try(self.wt.accept_proposals)
        if ok and isinstance(created, list):
            self.reload()
            self.notify(f"Created {len(created)} cluster(s)")

    def _model_name_thread(self, cid: str) -> None:
        try:
            name = self.wt.model_cluster_name(cid)
            error = None
        except (core.CoreError, RuntimeError, IndexError) as exc:
            name, error = "", str(exc)
        self.call_from_thread(self._model_name_done, cid, name, error)

    def _model_name_done(self, cid: str, name: str, error: str | None) -> None:
        self._busy.pop(f"cluster:{cid}", None)
        self.reload()
        if error:
            self.notify(f"Naming failed: {error}", severity="error", timeout=10)
        else:
            self.notify(f"Cluster named: {name}")


def run() -> None:
    """Start the terminal UI."""
    WebTreeApp().run()
