import pathlib
import time

import pytest
from fastapi import testclient

from tests import conftest
from webtree import core, web


@pytest.fixture
def client(wt: core.Core) -> testclient.TestClient:
    return testclient.TestClient(web.create_app(wt), base_url="http://127.0.0.1", headers={"x-webtree": "1"})


def _wait_reviews(client: testclient.TestClient, review_ids: list[str], timeout: float = 30.0) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        reviews = [client.get(f"/api/reviews/{rid}").json() for rid in review_ids]
        if all(r["status"] in ("done", "error") and not r["running"] for r in reviews):
            return reviews
        time.sleep(0.05)
    raise AssertionError("reviews did not finish")


def _place(client: testclient.TestClient, session_id: str, parent: str = core.SUN) -> str:
    response = client.post("/api/place", json={"session_id": session_id, "parent": parent})
    assert response.status_code == 200, response.text
    return response.json()["node_id"]


def test_static_frontend(client: testclient.TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "<canvas" in index.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_guard_rejects_foreign_host_and_missing_header(wt: core.Core) -> None:
    app = web.create_app(wt)
    foreign = testclient.TestClient(app, base_url="http://evil.example")
    assert foreign.get("/api/view").status_code == 403
    no_header = testclient.TestClient(app, base_url="http://localhost")
    assert no_header.get("/api/view").status_code == 200
    assert no_header.post("/api/place", json={"session_id": "aaaa0001", "parent": "sun"}).status_code == 403


def test_view_pulse_and_bin(client: testclient.TestClient) -> None:
    view = client.get("/api/view").json()
    assert view["nodes"] == {}
    assert {b["session_id"] for b in view["bin"]} == {"aaaa0001", "aaaa0002", "bbbb0001"}
    assert len(view["palettes"]["master"]) == 16
    assert view["busy"] == {"instantiate": [], "model_name": [], "reviews": []}
    pulse = client.get("/api/pulse").json()
    assert pulse["mtime"] == 0.0
    _place(client, "aaaa0001")
    assert client.get("/api/pulse").json()["mtime"] > 0


def test_sun_view_and_file(client: testclient.TestClient, claude_home: pathlib.Path) -> None:
    sun = client.get("/api/sun").json()
    assert "content" not in sun["overall"][0]
    assert set(sun["projects"]) == {"-repo-a", "-repo-b"}
    one = client.get("/api/sun", params={"project": "-repo-a", "content": True}).json()
    assert list(one["projects"]) == ["-repo-a"]
    memory = str(claude_home / "projects" / "-repo-a" / "memory" / "feedback_sol.md")
    found = client.get("/api/sun/file", params={"path": memory, "project": "-repo-a"}).json()
    assert found["content"] == "SOL means one line.\n"
    settings = client.get("/api/sun/file", params={"path": str(claude_home / "settings.json")}).json()
    assert "opus" in settings["content"]
    assert client.get("/api/sun/file", params={"path": "/etc/passwd"}).status_code == 404


def test_session_preview_stats_transcript_summary(client: testclient.TestClient) -> None:
    preview = client.get("/api/sessions/bbbb0001").json()
    assert preview["title"] == "Build Webtree GUI"
    assert preview["summaries"]["brief"] is None
    stats = client.get("/api/sessions/bbbb0001/stats").json()
    assert stats["lifetime_tokens"] == 700_000
    assert stats["tier_name"] == "jupiter"
    assert stats["file_size_mb"] >= 0
    transcript = client.get("/api/sessions/aaaa0001/transcript").json()
    assert "## User" in transcript["text"]
    assert client.get("/api/sessions/aaaa0001/summary", params={"cached_only": True}).json()["summary"] is None
    summary = client.get("/api/sessions/aaaa0001/summary").json()
    assert "FAKE OUTPUT" in summary["summary"]
    assert client.get("/api/sessions/aaaa0001").json()["summaries"]["brief"] == summary["summary"]
    assert client.get("/api/sessions/aaaa0001/summary", params={"level": "bogus"}).status_code == 400
    assert client.get("/api/sessions/nope").status_code == 400


def test_place_suggest_move_unplace(client: testclient.TestClient) -> None:
    root = _place(client, "aaaa0001")
    suggestions = client.get("/api/sessions/aaaa0002/suggest").json()
    assert suggestions[0]["parent"] == root
    assert suggestions[-1]["parent"] == core.SUN
    child = _place(client, "aaaa0002", root)
    duplicate = client.post("/api/place", json={"session_id": "aaaa0002", "parent": root})
    assert duplicate.status_code == 400
    assert "already placed" in duplicate.json()["detail"]
    assert client.post(f"/api/nodes/{root}/move", json={"parent": child}).status_code == 400
    assert client.post(f"/api/nodes/{child}/move", json={"parent": core.SUN}).status_code == 200
    assert client.get("/api/view").json()["nodes"][child]["parent"] == core.SUN
    assert client.post(f"/api/nodes/{child}/unplace").status_code == 200
    view = client.get("/api/view").json()
    assert child not in view["nodes"]
    assert "aaaa0002" in {b["session_id"] for b in view["bin"]}


def test_clouds_stage_update_discard_instantiate(client: testclient.TestClient, tmp_path: pathlib.Path) -> None:
    root = _place(client, "aaaa0001")
    cloud = client.post(f"/api/nodes/{root}/stage", json={"note": "try it"}).json()["node_id"]
    assert client.post(f"/api/nodes/{cloud}/cloud", json={"note": "renamed", "palette": "blue-navy"}).status_code == 200
    node = client.get("/api/view").json()["nodes"][cloud]
    assert (node["kind"], node["note"], node["palette"]) == ("cloud", "renamed", "blue-navy")
    assert client.post(f"/api/nodes/{root}/discard").status_code == 400
    assert client.post(f"/api/nodes/{root}/stage", json={"method": "teleport"}).status_code == 400
    response = client.post(f"/api/nodes/{cloud}/instantiate", json={"palette": "red-purple"})
    assert response.status_code == 200, response.text
    node = client.get("/api/view").json()["nodes"][cloud]
    assert node["kind"] == "planet"
    assert node["session_id"] == response.json()["session_id"]
    assert node["palette"] == "red-purple"
    assert "--fork-session" in conftest.calls(tmp_path)[-1]
    other = client.post(f"/api/nodes/{root}/stage", json={}).json()["node_id"]
    assert client.post(f"/api/nodes/{other}/discard").status_code == 200
    assert other not in client.get("/api/view").json()["nodes"]


def test_instantiate_failure(client: testclient.TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _place(client, "aaaa0001")
    cloud = client.post(f"/api/nodes/{root}/stage", json={}).json()["node_id"]
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    response = client.post(f"/api/nodes/{cloud}/instantiate", json={})
    assert response.status_code == 400
    assert "boom" in response.json()["detail"]
    view = client.get("/api/view").json()
    assert view["nodes"][cloud]["kind"] == "cloud"
    assert "boom" in view["nodes"][cloud]["error"]
    assert view["busy"]["instantiate"] == []


def test_split_palette_note_signal_open_command(client: testclient.TestClient) -> None:
    root = _place(client, "bbbb0001")
    clouds = client.post(f"/api/nodes/{root}/split", json={"focuses": ["frontend", " backend ", ""]}).json()["node_ids"]
    assert len(clouds) == 2
    assert client.post(f"/api/nodes/{root}/split", json={"focuses": ["only"]}).status_code == 400
    assert client.post(f"/api/nodes/{root}/palette", json={"palette": "pink-purple"}).status_code == 200
    assert client.post(f"/api/nodes/{root}/palette", json={"palette": "plaid"}).status_code == 400
    assert client.post(f"/api/nodes/{root}/note", json={"note": "hello"}).status_code == 200
    node = client.get("/api/view").json()["nodes"][root]
    assert (node["palette"], node["note"], node["badge"]) == ("pink-purple", "hello", True)
    assert client.post("/api/signals", json={"name": "jupiter_badge", "enabled": False}).status_code == 200
    view = client.get("/api/view").json()
    assert view["signals"]["jupiter_badge"] is False
    assert view["nodes"][root]["badge"] is False
    command = client.get(f"/api/nodes/{root}/open_command").json()["command"]
    assert "--resume bbbb0001" in command
    assert client.get(f"/api/nodes/{clouds[0]}/open_command").status_code == 400
    assert client.post("/api/nodes/missing/note", json={"note": "x"}).status_code == 400


def test_clusters(client: testclient.TestClient, wt: core.Core, monkeypatch: pytest.MonkeyPatch) -> None:
    a = _place(client, "aaaa0001")
    b = _place(client, "aaaa0002")
    other = _place(client, "bbbb0001")
    proposals = client.get("/api/clusters/proposals").json()
    assert len(proposals) == 1 and set(proposals[0]["members"]) == {a, b}
    [cluster] = client.post("/api/clusters/accept").json()["cluster_ids"]
    assert client.get("/api/view").json()["nodes"][a]["cluster"] == cluster
    assert client.post(f"/api/clusters/{cluster}/rename", json={"name": "too short"}).status_code == 400
    name = "Flatsat power and battery emulator sessions"
    assert client.post(f"/api/clusters/{cluster}/rename", json={"name": name}).status_code == 200
    assert client.get("/api/view").json()["clusters"][cluster]["name"] == name
    assert client.post(f"/api/nodes/{other}/cluster", json={"cluster_id": cluster}).status_code == 400
    assert client.post(f"/api/nodes/{b}/cluster", json={"cluster_id": None}).status_code == 200
    assert client.get("/api/view").json()["clusters"][cluster]["members"] == [a]
    assert client.post(f"/api/nodes/{b}/cluster", json={"cluster_id": cluster}).status_code == 200
    trimmed = client.post(f"/api/clusters/{cluster}/model_name")
    assert trimmed.status_code == 200 and len(trimmed.json()["name"].split()) <= 10
    monkeypatch.setattr(wt, "_ask", lambda *args: '"Flatsat power bring-up and battery emulation"\n')
    modelled = client.post(f"/api/clusters/{cluster}/model_name").json()
    assert modelled["name"] == "Flatsat power bring-up and battery emulation"
    assert client.get("/api/view").json()["busy"]["model_name"] == []
    assert client.post(f"/api/clusters/{cluster}/dissolve").status_code == 200
    assert client.get("/api/view").json()["clusters"] == {}
    created = client.post("/api/clusters", json={"project": "-repo-a", "name": name, "members": [a, b]})
    assert created.status_code == 200
    bad = client.post("/api/clusters", json={"project": "-repo-a", "name": name, "members": [other]})
    assert bad.status_code == 400
    assert client.post("/api/clusters/k-nope/dissolve").status_code == 400


def test_pull_levels(client: testclient.TestClient) -> None:
    a = _place(client, "aaaa0001")
    b = _place(client, "bbbb0001")
    full = client.post("/api/pull", json={"source": a, "target": b, "level": "full"}).json()
    assert "Power On Flatsat Integration" in pathlib.Path(full["file"]).read_text()
    assert full["file"] in full["prompt"]
    compacted = client.post("/api/pull", json={"source": a, "target": b}).json()
    assert "FAKE OUTPUT" in pathlib.Path(compacted["file"]).read_text()
    assert client.post("/api/pull", json={"source": a, "target": b, "level": "huge"}).status_code == 400
    cloud = client.post(f"/api/nodes/{a}/stage", json={}).json()["node_id"]
    assert client.post("/api/pull", json={"source": a, "target": cloud}).status_code == 400
    c = _place(client, "aaaa0002")
    cluster = client.post(
        "/api/clusters",
        json={"project": "-repo-a", "name": "Flatsat power and battery emulator work", "members": [a, c]},
    ).json()["cluster_id"]
    cluster_pull = client.post("/api/pull", json={"source": cluster, "target": b}).json()
    assert "cluster" in pathlib.Path(cluster_pull["file"]).read_text()
    levels = {p["level"] for p in client.get("/api/view").json()["pulls"]}
    assert levels == {"full", "compacted", "cluster_summary"}


def test_parallel_reviews(client: testclient.TestClient) -> None:
    a = _place(client, "aaaa0001")
    b = _place(client, "aaaa0002")
    ids = [
        client.post("/api/reviews", json={"target": a, "problem": "Is the design right?"}).json()["review_id"],
        client.post("/api/reviews", json={"target": a, "problem": "Same", "reviewer": b}).json()["review_id"],
        client.post("/api/reviews", json={"target": a, "problem": "No context", "include": "none"}).json()["review_id"],
    ]
    done = _wait_reviews(client, ids)
    assert [r["status"] for r in done] == ["done", "done", "done"]
    assert len([r for r in client.get("/api/view").json()["reviews"] if r["target"] == a]) == 3
    prompt = client.get(f"/api/reviews/{ids[0]}/prompt").json()["prompt"]
    assert done[0]["file"] in prompt


def test_reviews_run_concurrently(
    client: testclient.TestClient, wt: core.Core, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _place(client, "aaaa0001")
    original = wt.run_review

    def slow_review(review_id: str) -> dict:
        time.sleep(0.5)
        return original(review_id)

    monkeypatch.setattr(wt, "run_review", slow_review)
    start = time.time()
    ids = [
        client.post("/api/reviews", json={"target": a, "problem": f"p{i}", "include": "none"}).json()["review_id"]
        for i in range(4)
    ]
    assert set(client.get("/api/view").json()["busy"]["reviews"]) == set(ids)
    done = _wait_reviews(client, ids)
    assert all(r["status"] == "done" for r in done)
    assert time.time() - start < 1.8


def test_review_errors(client: testclient.TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    a = _place(client, "aaaa0001")
    cloud = client.post(f"/api/nodes/{a}/stage", json={}).json()["node_id"]
    assert client.post("/api/reviews", json={"target": cloud, "problem": "x"}).status_code == 400
    assert client.post("/api/reviews", json={"target": a, "problem": "x", "include": "all"}).status_code == 400
    assert client.post("/api/reviews", json={"target": a, "problem": "x", "reviewer": cloud}).status_code == 400
    assert client.get("/api/reviews/rev-nope").status_code == 400
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    rid = client.post("/api/reviews", json={"target": a, "problem": "x", "include": "none"}).json()["review_id"]
    [failed] = _wait_reviews(client, [rid])
    assert failed["status"] == "error" and "boom" in failed["error"]
    assert client.get(f"/api/reviews/{rid}/prompt").status_code == 400
    monkeypatch.delenv("FAKE_CLAUDE_FAIL")
    assert client.post(f"/api/reviews/{rid}/run").status_code == 200
    [retried] = _wait_reviews(client, [rid])
    assert retried["status"] == "done"


def test_side_by_side_group_endpoints(client: testclient.TestClient) -> None:
    a = client.post("/api/place", json={"session_id": "aaaa0001", "parent": "sun"}).json()["node_id"]
    b = client.post("/api/place", json={"session_id": "aaaa0002", "parent": "sun"}).json()["node_id"]
    c = client.post("/api/place", json={"session_id": "bbbb0001", "parent": a}).json()["node_id"]
    group = client.post("/api/groups", json={"node_ids": [a, b]}).json()["group_id"]
    assert client.get("/api/view").json()["nodes"][b]["group"] == group
    assert client.post("/api/groups", json={"node_ids": [b, c]}).status_code == 200
    assert client.get("/api/view").json()["nodes"][c]["parent"] == "sun"
    assert client.post(f"/api/nodes/{a}/ungroup").status_code == 200
    assert client.post(f"/api/nodes/{c}/ungroup").status_code == 200
    nodes = client.get("/api/view").json()["nodes"]
    assert nodes[b]["group"] is None and nodes[c]["parent"] == a


def test_group_parent_endpoint(client: testclient.TestClient) -> None:
    a = client.post("/api/place", json={"session_id": "aaaa0001", "parent": "sun"}).json()["node_id"]
    b = client.post("/api/place", json={"session_id": "aaaa0002", "parent": "sun"}).json()["node_id"]
    c = client.post("/api/place", json={"session_id": "bbbb0001", "parent": a}).json()["node_id"]
    group = client.post("/api/groups", json={"node_ids": [a, b]}).json()["group_id"]
    assert client.post(f"/api/nodes/{c}/group_parent", json={"group_id": group}).status_code == 200
    assert client.get("/api/view").json()["nodes"][c]["group_parent"] == group
    assert client.post(f"/api/nodes/{a}/group_parent", json={"group_id": group}).status_code == 400
    assert client.post(f"/api/nodes/{c}/group_parent", json={"group_id": None}).status_code == 200
