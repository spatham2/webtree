import pathlib

import pytest

from tests import conftest
from webtree import core, sessions


def test_sessions_parsed(wt: core.Core) -> None:
    all_sessions = wt.list_sessions()
    assert set(all_sessions) == {"aaaa0001", "aaaa0002", "bbbb0001"}
    s = all_sessions["bbbb0001"]
    assert s.title == "Build Webtree GUI"
    assert s.title_source == "custom"
    assert s.context_tokens == 700_000
    assert s.lifetime_tokens == 700_000
    assert s.file_size > 0


def test_unplaced_sessions_go_to_bin(wt: core.Core) -> None:
    view = wt.view()
    assert view["nodes"] == {}
    assert {b["session_id"] for b in view["bin"]} == {"aaaa0001", "aaaa0002", "bbbb0001"}


def test_place_and_suggest(wt: core.Core) -> None:
    root = wt.place("aaaa0001", core.SUN)
    suggestions = wt.suggest_parents("aaaa0002")
    assert suggestions[0]["parent"] == root
    assert "same project" in suggestions[0]["reasons"]
    assert suggestions[-1]["parent"] == core.SUN
    child = wt.place("aaaa0002", root)
    view = wt.view()
    assert view["nodes"][child]["parent"] == root
    assert [b["session_id"] for b in view["bin"]] == ["bbbb0001"]
    with pytest.raises(core.CoreError):
        wt.place("aaaa0002", root)


def test_tiers(wt: core.Core) -> None:
    node = wt.place("bbbb0001", core.SUN)
    item = wt.view()["nodes"][node]
    assert item["tier_name"] == "jupiter"
    assert item["badge"] is True
    wt.set_signal("jupiter_badge", False)
    assert wt.view()["nodes"][node]["badge"] is False


def test_stage_and_instantiate_fork(wt: core.Core, tmp_path: pathlib.Path) -> None:
    root = wt.place("aaaa0001", core.SUN)
    cloud = wt.stage(root, note="try a different approach", palette="red-purple")
    assert wt.view()["nodes"][cloud]["kind"] == "cloud"
    new_id = wt.instantiate(cloud)
    node = wt.view()["nodes"][cloud]
    assert node["kind"] == "planet"
    assert node["session_id"] == new_id
    assert node["palette"] == "red-purple"
    fork_call = conftest.calls(tmp_path)[-1]
    assert "--fork-session" in fork_call and "aaaa0001" in fork_call


def test_instantiate_failure_stays_cloud(wt: core.Core, monkeypatch: pytest.MonkeyPatch) -> None:
    root = wt.place("aaaa0001", core.SUN)
    cloud = wt.stage(root)
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    with pytest.raises(core.CoreError):
        wt.instantiate(cloud)
    node = wt.view()["nodes"][cloud]
    assert node["kind"] == "cloud"
    assert "boom" in node["error"]


def test_discard_and_move(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", a)
    with pytest.raises(core.CoreError):
        wt.move(a, b)
    wt.move(b, core.SUN)
    cloud = wt.stage(a)
    wt.discard(cloud)
    assert cloud not in wt.view()["nodes"]


def test_split_stages_clouds(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    clouds = wt.split(a, ["frontend", "backend"])
    nodes = wt.view()["nodes"]
    assert all(nodes[c]["kind"] == "cloud" for c in clouds)
    assert "frontend" in nodes[clouds[0]]["note"]


def test_clusters_by_topic_within_project(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", core.SUN)
    wt.place("bbbb0001", core.SUN)
    proposals = wt.propose_clusters()
    assert len(proposals) == 1
    assert set(proposals[0]["members"]) == {a, b}
    assert 5 <= len(proposals[0]["name"].split()) <= 10
    [cluster] = wt.accept_proposals()
    assert wt.view()["nodes"][a]["cluster"] == cluster
    with pytest.raises(core.CoreError):
        wt.rename_cluster(cluster, "too short")


def test_pull_full_and_cluster(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("bbbb0001", core.SUN)
    result = wt.pull(a, b, "full")
    body = pathlib.Path(result["file"]).read_text()
    assert "Power On Flatsat Integration" in body
    assert result["file"] in result["prompt"]
    compacted = wt.pull(a, b, "compacted")
    assert "FAKE OUTPUT" in pathlib.Path(compacted["file"]).read_text()
    c = wt.place("aaaa0002", core.SUN)
    cluster = wt.create_cluster("-repo-a", "Flatsat power and battery emulator work", [a, c])
    cluster_pull = wt.pull(cluster, b)
    assert "cluster" in pathlib.Path(cluster_pull["file"]).read_text()
    assert {p["level"] for p in wt.view()["pulls"]} == {"full", "compacted", "cluster_summary"}


def test_summary_cached(wt: core.Core, tmp_path: pathlib.Path) -> None:
    wt.summary("aaaa0001", "compacted")
    count = len(conftest.calls(tmp_path))
    wt.summary("aaaa0001", "compacted")
    assert len(conftest.calls(tmp_path)) == count


def test_parallel_reviews(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", core.SUN)
    r1 = wt.start_review(a, "Is the emulator design right?")
    r2 = wt.start_review(a, "Same problem", reviewer=b)
    done1, done2 = wt.run_review(r1), wt.run_review(r2)
    assert done1["status"] == done2["status"] == "done"
    assert len([r for r in wt.view()["reviews"] if r["target"] == a]) == 2
    assert done1["file"] in wt.review_prompt(r1)


def test_sun_layers(wt: core.Core) -> None:
    view = wt.sun_view()
    assert [f["group"] for f in view["overall"]] == ["config", "instructions"]
    assert any(f["path"].endswith("feedback_sol.md") for f in view["projects"]["-repo-a"])
    assert view["projects"]["-repo-b"] == []


def test_sun_drift(wt: core.Core, claude_home: pathlib.Path) -> None:
    a = wt.place("aaaa0001", core.SUN)
    assert wt.view()["nodes"][a]["sun_drift"] is False
    (claude_home / "projects" / "-repo-a" / "memory" / "new.md").write_text("new memory")
    assert wt.view()["nodes"][a]["sun_drift"] is True


def test_render_transcript(wt: core.Core) -> None:
    text = sessions.render_transcript(wt.session("aaaa0001").path)
    assert "## User" in text and "## Assistant" in text


def test_cached_summary_never_calls_model(wt: core.Core, tmp_path: pathlib.Path) -> None:
    assert wt.cached_summary("aaaa0001", "brief") is None
    assert conftest.calls(tmp_path) == []
    text = wt.summary("aaaa0001", "brief")
    assert wt.cached_summary("aaaa0001", "brief") == text


def test_unknown_cluster_is_core_error(wt: core.Core) -> None:
    with pytest.raises(core.CoreError):
        wt.dissolve_cluster("k-nope")
    with pytest.raises(core.CoreError):
        wt.rename_cluster("k-nope", "one two three four five")


def test_review_summary_failure_marks_error(wt: core.Core, monkeypatch: pytest.MonkeyPatch) -> None:
    a = wt.place("aaaa0001", core.SUN)
    review = wt.start_review(a, "problem")
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    assert wt.run_review(review)["status"] == "error"


def test_model_cluster_name_trims_and_falls_back(wt: core.Core, monkeypatch: pytest.MonkeyPatch) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", core.SUN)
    cluster = wt.create_cluster("-repo-a", "Flatsat power and battery emulator work", [a, b])
    monkeypatch.setattr(
        wt, "_ask", lambda *args, **kwargs: "one two three four five six seven eight nine ten eleven twelve"
    )
    assert len(wt.model_cluster_name(cluster).split()) == 10
    monkeypatch.setattr(wt, "_ask", lambda *args, **kwargs: "Flatsat")
    assert 5 <= len(wt.model_cluster_name(cluster).split()) <= 10


def test_side_by_side_groups(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", core.SUN)
    group = wt.group_siblings([a, b])
    nodes = wt.view()["nodes"]
    assert nodes[a]["group"] == nodes[b]["group"] == group
    with pytest.raises(core.CoreError):
        wt.group_siblings([a])
    cloud = wt.stage(a)
    wt.move(cloud, core.SUN)
    assert wt.group_siblings([cloud, a]) == group
    wt.ungroup(cloud)
    assert wt.view()["nodes"][a]["group"] == group
    wt.move(b, a)
    nodes = wt.view()["nodes"]
    assert nodes[a]["group"] is None and nodes[b]["group"] is None


def test_group_any_planets_keeps_downstream(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", a)
    c = wt.place("bbbb0001", core.SUN)
    child_of_b = wt.stage(b, note="downstream of b")
    group = wt.group_siblings([c, b])
    nodes = wt.view()["nodes"]
    assert nodes[b]["parent"] == core.SUN == nodes[c]["parent"]
    assert nodes[b]["group"] == nodes[c]["group"] == group
    assert nodes[child_of_b]["parent"] == b
    wt.ungroup(b)
    nodes = wt.view()["nodes"]
    assert nodes[b]["parent"] == a and nodes[b]["group"] is None
    assert nodes[c]["group"] is None


def test_ask_failure_is_core_error(wt: core.Core, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    with pytest.raises(core.CoreError):
        wt.summary("aaaa0001", "brief")


def test_group_with_descendant_keeps_both_subtrees(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", a)
    c = wt.place("bbbb0001", b)
    sibling_of_b = wt.stage(a, note="other child of a")
    group = wt.group_siblings([a, b])
    nodes = wt.view()["nodes"]
    assert nodes[a]["parent"] == nodes[b]["parent"] == core.SUN
    assert nodes[a]["group"] == nodes[b]["group"] == group
    assert nodes[c]["parent"] == b
    assert nodes[sibling_of_b]["parent"] == a
    wt.ungroup(b)
    assert wt.view()["nodes"][b]["parent"] == a


def test_group_ancestor_onto_descendant(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", a)
    c = wt.place("bbbb0001", b)
    wt.group_siblings([c, a])
    nodes = wt.view()["nodes"]
    assert nodes[a]["parent"] == nodes[c]["parent"] == core.SUN
    assert nodes[b]["parent"] == a
    wt.move(a, core.SUN)


def test_children_of_whole_group(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", core.SUN)
    own_child = wt.stage(a, note="already under a")
    group = wt.group_siblings([a, b])
    nodes = wt.view()["nodes"]
    assert nodes[own_child]["parent"] == a and not nodes[own_child].get("group_parent")
    shared = wt.place("bbbb0001", b)
    wt.set_group_parent(shared, group)
    assert wt.view()["nodes"][shared]["group_parent"] == group
    with pytest.raises(core.CoreError):
        wt.set_group_parent(a, group)
    wt.ungroup(b)
    nodes = wt.view()["nodes"]
    assert nodes[shared]["parent"] in (a, b)
    assert not nodes[shared].get("group_parent")


def test_group_child_moves_when_member_leaves(wt: core.Core) -> None:
    a = wt.place("aaaa0001", core.SUN)
    b = wt.place("aaaa0002", core.SUN)
    c = wt.stage(a, note="third member")
    wt.move(c, core.SUN)
    group = wt.group_siblings([a, b, c])
    shared = wt.place("bbbb0001", a)
    wt.set_group_parent(shared, group)
    wt.unplace(a)
    nodes = wt.view()["nodes"]
    assert nodes[shared]["parent"] in (b, c)
    assert nodes[shared]["group_parent"] == group
    wt.set_group_parent(shared, None)
    assert not wt.view()["nodes"][shared].get("group_parent")
