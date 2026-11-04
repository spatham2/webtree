import asyncio
import io
import pathlib
from collections.abc import Callable, Coroutine

import pytest
from rich import console
from textual import pilot as pilot_mod
from textual import widgets

from webtree import core, tui


def make_app(wt: core.Core, copied: list[str] | None = None, opened: list[str] | None = None) -> tui.WebTreeApp:
    sink = copied if copied is not None else []
    opens = opened if opened is not None else []

    def clipboard(value: str) -> bool:
        sink.append(value)
        return True

    return tui.WebTreeApp(wt, opener=opens.append, clipboard=clipboard, poll_interval=0.2)


def run(coro_factory: Callable[[], Coroutine[object, object, None]]) -> None:
    asyncio.run(coro_factory())


async def select_node(app: tui.WebTreeApp, pilot: pilot_mod.Pilot, key: tui.Key) -> None:
    app.tree.move_cursor(app._tnodes[key])
    await pilot.pause()


async def wait_until(pilot: pilot_mod.Pilot, condition: Callable[[], bool], timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await pilot.pause(0.05)


def side_plain(app: tui.WebTreeApp) -> str:
    con = console.Console(width=200, record=True, file=io.StringIO())
    side = app.query_one("#side", widgets.Static)
    con.print(getattr(side, "content", None) or side.renderable)
    return con.export_text()


def test_starts_with_sun_and_bin(wt: core.Core) -> None:
    async def body() -> None:
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            assert app.tree.root.data == tui.SUN_KEY
            assert "Head" in str(app.tree.root.label)
            assert app.bin_list.option_count == 3
            assert "Overall layer" in side_plain(app)

    run(body)


def test_place_binned_session_via_keys(wt: core.Core) -> None:
    async def body() -> None:
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.press("b")
            assert app.focused is app.bin_list
            ids = [app.bin_list.get_option_at_index(i).id for i in range(app.bin_list.option_count)]
            app.bin_list.highlighted = ids.index("aaaa0001")
            await pilot.pause()
            assert "Power On Flatsat Integration" in side_plain(app)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.ChoiceModal)
            await pilot.press("end", "enter")
            await pilot.pause()
            assert app._pending is not None
            await select_node(app, pilot, tui.SUN_KEY)
            await pilot.press("enter")
            await pilot.pause()
            placed = {n["session_id"] for n in wt.view()["nodes"].values()}
            assert placed == {"aaaa0001"}
            app.bin_list.focus()
            ids = [app.bin_list.get_option_at_index(i).id for i in range(app.bin_list.option_count)]
            app.bin_list.highlighted = ids.index("aaaa0002")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            view = wt.view()
            parent_node = next(nid for nid, n in view["nodes"].items() if n["session_id"] == "aaaa0001")
            child = next(n for n in view["nodes"].values() if n["session_id"] == "aaaa0002")
            assert child["parent"] == parent_node
            assert app.bin_list.option_count == 1

    run(body)


def test_fork_and_instantiate_via_keys(wt: core.Core) -> None:
    async def body() -> None:
        root = wt.place("aaaa0001", core.SUN)
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await select_node(app, pilot, ("node", root))
            await pilot.press("f")
            await pilot.pause()
            await pilot.press(*"try sqlite", "enter")
            await pilot.pause()
            clouds = [nid for nid, n in wt.view()["nodes"].items() if n["kind"] == "cloud"]
            assert len(clouds) == 1
            assert app.current_key() == ("node", clouds[0])
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, tui.ChoiceModal)
            await pilot.press("down", "enter")
            await wait_until(pilot, lambda: wt.view()["nodes"][clouds[0]]["kind"] == "planet" and not app._busy)
            node = wt.view()["nodes"][clouds[0]]
            assert node["session_id"]
            assert node["palette"]
            assert ("node", clouds[0]) in app._tnodes

    run(body)


def test_instantiate_failure_shows_error(wt: core.Core, monkeypatch: pytest.MonkeyPatch) -> None:
    async def body() -> None:
        root = wt.place("aaaa0001", core.SUN)
        cloud = wt.stage(root, note="doomed")
        monkeypatch.setenv("FAKE_CODEX_FAIL", "1")
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await select_node(app, pilot, ("node", cloud))
            await pilot.press("i", "enter")
            await wait_until(pilot, lambda: not app._busy and "error" in wt.view()["nodes"][cloud])
            assert wt.view()["nodes"][cloud]["kind"] == "cloud"
            await pilot.pause()
            assert "boom" in side_plain(app)

    run(body)


def test_palette_change(wt: core.Core) -> None:
    async def body() -> None:
        root = wt.place("aaaa0001", core.SUN)
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await select_node(app, pilot, ("node", root))
            await pilot.press("c")
            await pilot.pause()
            choices = app.screen.query_one("#choices")
            target = list(tui.palettes.SCHEMES).index("pink-purple")
            choices.highlighted = target
            await pilot.press("enter")
            await pilot.pause()
            assert wt.view()["nodes"][root]["palette"] == "pink-purple"
            assert "Pink + purple" in side_plain(app)

    run(body)


def test_pull_flow_writes_pull_file(wt: core.Core) -> None:
    async def body() -> None:
        a = wt.place("aaaa0001", core.SUN)
        b = wt.place("bbbb0001", core.SUN)
        copied: list[str] = []
        app = make_app(wt, copied)
        async with app.run_test(size=(160, 50)) as pilot:
            await select_node(app, pilot, ("node", a))
            await pilot.press("p")
            assert app._pending is not None and app._pending.kind == "pull"
            await select_node(app, pilot, ("node", b))
            await pilot.press("p")
            await pilot.pause()
            assert isinstance(app.screen, tui.ChoiceModal)
            await pilot.press("home", "enter")
            await wait_until(pilot, lambda: bool(copied))
            pulls = wt.view()["pulls"]
            assert len(pulls) == 1 and pulls[0]["level"] == "full"
            assert pathlib.Path(pulls[0]["file"]).is_file()
            assert pulls[0]["file"] in copied[0]
            await pilot.pause()
            assert isinstance(app.screen, tui.TextModal)
            await pilot.press("escape")
            await select_node(app, pilot, ("node", b))
            assert "Power On Flatsat Integration (full)" in side_plain(app)

    run(body)


def test_reviewer_flow_completes(wt: core.Core) -> None:
    async def body() -> None:
        a = wt.place("aaaa0001", core.SUN)
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            for problem in ("Is the design right?", "Second opinion"):
                await select_node(app, pilot, ("node", a))
                await pilot.press("r")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.press(*problem, "enter")
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
            await wait_until(
                pilot,
                lambda: len(wt.view()["reviews"]) == 2 and all(r["status"] == "done" for r in wt.view()["reviews"]),
            )
            await wait_until(pilot, lambda: app._reviews_running == 0)
            review = wt.view()["reviews"][0]
            assert ("review", review["id"]) in app._tnodes
            await select_node(app, pilot, ("review", review["id"]))
            assert "done" in side_plain(app)

    run(body)


def test_filter(wt: core.Core) -> None:
    async def body() -> None:
        wt.place("aaaa0001", core.SUN)
        wt.place("bbbb0001", core.SUN)
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            assert len(app.tree.root.children) == 2
            await pilot.press("slash", *"webtree")
            await pilot.pause()
            assert len(app.tree.root.children) == 1
            assert "Webtree" in str(app.tree.root.children[0].label)
            assert app.bin_list.option_count == 0
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.tree.root.children) == 2
            assert app.bin_list.option_count == 1

    run(body)


def test_cluster_accept(wt: core.Core) -> None:
    async def body() -> None:
        a = wt.place("aaaa0001", core.SUN)
        b = wt.place("aaaa0002", core.SUN)
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.press("K")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.ChoiceModal)
            await pilot.press("enter")
            await pilot.pause()
            clusters = wt.view()["clusters"]
            assert len(clusters) == 1
            [cid] = clusters
            assert set(clusters[cid]["members"]) == {a, b}
            cnode = app._tnodes[("cluster", cid)]
            assert {c.data for c in cnode.children} == {("node", a), ("node", b)}

    run(body)


def test_open_and_external_change_reload(wt: core.Core) -> None:
    async def body() -> None:
        a = wt.place("aaaa0001", core.SUN)
        opened: list[str] = []
        app = make_app(wt, opened=opened)
        async with app.run_test(size=(160, 50)) as pilot:
            await select_node(app, pilot, ("node", a))
            await pilot.press("enter")
            assert opened and " resume aaaa0001" in opened[0]
            other = core.Core(wt.cfg)
            other.place("bbbb0001", core.SUN)
            await wait_until(pilot, lambda: app.bin_list.option_count == 1)

    run(body)


def test_double_click_copies_resume_command(wt: core.Core) -> None:
    async def body() -> None:
        a = wt.place("aaaa0001", core.SUN)
        copied: list[str] = []
        app = make_app(wt, copied=copied)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            line = app._tnodes[("node", a)].line
            await pilot.click("#tree", offset=(8, line + 1), times=2)
            await wait_until(pilot, lambda: bool(copied))
            assert copied[-1].endswith(" resume aaaa0001")
            assert app.resume_command(tui.SUN_KEY) is None

    run(body)


def test_side_by_side_join_and_separate(wt: core.Core) -> None:
    async def body() -> None:
        a = wt.place("aaaa0001", core.SUN)
        b = wt.place("aaaa0002", core.SUN)
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await select_node(app, pilot, ("node", a))
            await pilot.press("g")
            await pilot.pause()
            assert isinstance(app.screen, tui.ChoiceModal)
            await pilot.press("enter")
            await wait_until(pilot, lambda: wt.view()["nodes"][a].get("group") is not None)
            assert wt.view()["nodes"][b]["group"] == wt.view()["nodes"][a]["group"]
            assert "┃" in str(app._tnodes[("node", b)].label)
            assert "Group" in side_plain(app)
            await select_node(app, pilot, ("node", a))
            await pilot.press("g")
            await pilot.pause()
            await pilot.press("enter")
            await wait_until(pilot, lambda: wt.view()["nodes"][a].get("group") is None)

    run(body)


def test_group_with_planet_from_another_branch(wt: core.Core) -> None:
    async def body() -> None:
        a = wt.place("aaaa0001", core.SUN)
        b = wt.place("aaaa0002", a)
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await select_node(app, pilot, ("node", a))
            app.reload(("node", a))
            await pilot.pause()
            c = wt.place("bbbb0001", core.SUN)
            app.reload(("node", c))
            await select_node(app, pilot, ("node", c))
            await pilot.press("g")
            await pilot.pause()
            assert isinstance(app.screen, tui.ChoiceModal)
            option_list = app.screen.query_one(widgets.OptionList)
            ids = [option_list.get_option_at_index(i).id for i in range(option_list.option_count)]
            assert b in ids
            option_list.highlighted = ids.index(b)
            await pilot.press("enter")
            await wait_until(pilot, lambda: wt.view()["nodes"][b].get("group") is not None)
            assert wt.view()["nodes"][b]["parent"] == core.SUN

    run(body)


def test_attach_child_to_whole_group(wt: core.Core) -> None:
    async def body() -> None:
        a = wt.place("aaaa0001", core.SUN)
        b = wt.place("aaaa0002", core.SUN)
        c = wt.place("bbbb0001", a)
        group = wt.group_siblings([a, b])
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await select_node(app, pilot, ("node", c))
            await pilot.press("a")
            await wait_until(pilot, lambda: wt.view()["nodes"][c].get("group_parent") == group)
            assert "Attached to" in side_plain(app)
            await select_node(app, pilot, ("node", c))
            await pilot.press("a")
            await wait_until(pilot, lambda: not wt.view()["nodes"][c].get("group_parent"))

    run(body)


async def click_border_link(pilot: pilot_mod.Pilot, selector: str, changed: Callable[[], bool]) -> None:
    for x in range(1, 40):
        await pilot.click(selector, offset=(x, 0))
        await pilot.pause()
        if changed():
            return
    raise AssertionError(f"no clickable border link on {selector}")


def test_minimize_details_and_bin(wt: core.Core) -> None:
    async def body() -> None:
        app = make_app(wt)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            right = app.query_one("#right")
            details = app.query_one("#side-scroll")
            await click_border_link(pilot, "#side-scroll", lambda: not details.display)
            assert right.display and app.query_one("#details-tab").display
            await click_border_link(pilot, "#bin", lambda: not app.bin_list.display)
            assert not right.display and app.query_one("#rail").display
            assert app.tree.size.width > 150
            await pilot.click("#rail")
            await pilot.pause()
            assert details.display and app.bin_list.display and not app.query_one("#rail").display
            await click_border_link(pilot, "#tree", lambda: not right.display)
            await click_border_link(pilot, "#tree", lambda: right.display)
            await click_border_link(pilot, "#side-scroll", lambda: not details.display)
            await pilot.click("#details-tab")
            await pilot.pause()
            assert details.display
            await pilot.press("T")
            await pilot.pause()
            assert not right.display
            await pilot.press("b")
            await pilot.pause()
            assert app.bin_list.display and not details.display

    run(body)
