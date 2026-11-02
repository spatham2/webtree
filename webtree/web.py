"""FastAPI backend for the web GUI. Wraps `core.Core`; binds to localhost only."""

import pathlib
import threading
from collections.abc import Callable
from typing import Any

import fastapi
import pydantic
import uvicorn
from fastapi import responses, staticfiles

from webtree import core, sessions

STATIC_DIR = pathlib.Path(__file__).parent / "static"
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
CSRF_HEADER = "x-webtree"
SUMMARY_LEVELS = ("brief", "compacted", "extra_compacted")


class PlaceBody(pydantic.BaseModel):
    session_id: str
    parent: str


class ParentBody(pydantic.BaseModel):
    parent: str


class StageBody(pydantic.BaseModel):
    method: str = "fork"
    note: str = ""
    palette: str | None = None


class CloudBody(pydantic.BaseModel):
    note: str | None = None
    palette: str | None = None


class PaletteBody(pydantic.BaseModel):
    palette: str


class OptionalPaletteBody(pydantic.BaseModel):
    palette: str | None = None


class NoteBody(pydantic.BaseModel):
    note: str


class SplitBody(pydantic.BaseModel):
    focuses: list[str]


class SignalBody(pydantic.BaseModel):
    name: str
    enabled: bool


class ClusterBody(pydantic.BaseModel):
    project: str
    name: str
    members: list[str]


class NameBody(pydantic.BaseModel):
    name: str


class ClusterMoveBody(pydantic.BaseModel):
    cluster_id: str | None = None


class GroupParentBody(pydantic.BaseModel):
    group_id: str | None = None


class GroupBody(pydantic.BaseModel):
    node_ids: list[str]


class PullBody(pydantic.BaseModel):
    source: str
    target: str
    level: str = "compacted"


class ReviewBody(pydantic.BaseModel):
    target: str
    problem: str
    reviewer: str = "fresh"
    include: str = "summary"


class Jobs:
    """Tracks long-running work so the view can show spinners and reviews run in parallel."""

    def __init__(self, wt: core.Core) -> None:
        self.wt = wt
        self._lock = threading.Lock()
        self._busy: dict[str, set[str]] = {"instantiate": set(), "model_name": set(), "reviews": set()}
        self.threads: dict[str, threading.Thread] = {}

    def busy(self) -> dict[str, list[str]]:
        with self._lock:
            return {kind: sorted(ids) for kind, ids in self._busy.items()}

    def claim(self, kind: str, key: str) -> None:
        with self._lock:
            if key in self._busy[kind]:
                raise core.CoreError(f"{key} is already running")
            self._busy[kind].add(key)

    def release(self, kind: str, key: str) -> None:
        with self._lock:
            self._busy[kind].discard(key)

    def run_claimed(self, kind: str, key: str, fn: Callable[[], Any]) -> Any:
        self.claim(kind, key)
        try:
            return fn()
        finally:
            self.release(kind, key)

    def start_review(self, review_id: str) -> None:
        self.claim("reviews", review_id)
        thread = threading.Thread(target=self._review_worker, args=(review_id,), daemon=True)
        self.threads[review_id] = thread
        thread.start()

    def _review_worker(self, review_id: str) -> None:
        try:
            self.wt.run_review(review_id)
        except Exception as exc:  # noqa: BLE001
            self.wt.fail_review(review_id, str(exc))
        finally:
            self.release("reviews", review_id)


def _session_stats(wt: core.Core, session_id: str) -> dict:
    s = wt.session(session_id)
    return {
        "session_id": s.session_id,
        "title": s.title,
        "lifetime_tokens": s.lifetime_tokens,
        "cache_read_tokens": s.cache_read_tokens,
        "context_tokens": s.context_tokens,
        "file_size": s.file_size,
        "file_size_mb": round(s.file_size / 1_000_000, 2),
        **wt.session_stats(s),
    }


def create_app(wt: core.Core) -> fastapi.FastAPI:
    """Build the FastAPI app around an injected Core."""
    app = fastapi.FastAPI(title="Web Tree")
    jobs = Jobs(wt)
    app.state.core = wt
    app.state.jobs = jobs

    @app.middleware("http")
    async def guard(request: fastapi.Request, call_next: Callable) -> fastapi.Response:
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS and host != "::1":
            return responses.JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "1":
            return responses.JSONResponse({"detail": f"missing {CSRF_HEADER} header"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(core.CoreError)
    async def core_error(_request: fastapi.Request, exc: core.CoreError) -> responses.JSONResponse:
        return responses.JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/")
    def index() -> responses.FileResponse:
        return responses.FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/view")
    def view() -> dict:
        data = wt.view()
        data["busy"] = jobs.busy()
        return data

    @app.get("/api/pulse")
    def pulse() -> dict:
        paths = wt.index.transcript_paths()
        newest = max((p.stat().st_mtime for p in paths if p.exists()), default=0.0)
        return {"mtime": wt.store.mtime(), "busy": jobs.busy(), "sessions": f"{len(paths)}:{newest}"}

    @app.get("/api/sun")
    def sun_view(project: str | None = None, content: bool = False) -> dict:
        return wt.sun_view(project, include_content=content)

    @app.get("/api/sun/file")
    def sun_file(path: str, project: str | None = None) -> dict:
        data = wt.sun_view(project, include_content=True)
        files = data["overall"] + [f for section in data["projects"].values() for f in section]
        found = next((f for f in files if f["path"] == path), None)
        if not found:
            raise fastapi.HTTPException(404, "not a sun file")
        return found

    @app.get("/api/sessions/{session_id}")
    def session_preview(session_id: str) -> dict:
        s = wt.session(session_id)
        return {
            **s.to_dict(),
            **_session_stats(wt, session_id),
            "summaries": {level: wt.cached_summary(session_id, level) for level in SUMMARY_LEVELS},
        }

    @app.get("/api/sessions/{session_id}/stats")
    def session_stats(session_id: str) -> dict:
        return _session_stats(wt, session_id)

    @app.get("/api/sessions/{session_id}/summary")
    def session_summary(session_id: str, level: str = "brief", cached_only: bool = False) -> dict:
        if level not in SUMMARY_LEVELS:
            raise core.CoreError(f"level must be one of {SUMMARY_LEVELS}")
        if cached_only:
            return {"level": level, "summary": wt.cached_summary(session_id, level)}
        return {"level": level, "summary": wt.summary(session_id, level)}

    @app.get("/api/sessions/{session_id}/transcript")
    def session_transcript(session_id: str, max_chars: int = 20_000) -> dict:
        text = sessions.render_transcript(wt.session(session_id).path)
        return {"text": text[:max_chars], "total_chars": len(text), "truncated": len(text) > max_chars}

    @app.get("/api/sessions/{session_id}/suggest")
    def suggest(session_id: str, limit: int = 5) -> list[dict]:
        return wt.suggest_parents(session_id, limit)

    @app.post("/api/place")
    def place(body: PlaceBody) -> dict:
        return {"node_id": wt.place(body.session_id, body.parent)}

    @app.post("/api/nodes/{node_id}/move")
    def move(node_id: str, body: ParentBody) -> dict:
        wt.move(node_id, body.parent)
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/unplace")
    def unplace(node_id: str) -> dict:
        wt.unplace(node_id)
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/stage")
    def stage(node_id: str, body: StageBody) -> dict:
        return {"node_id": wt.stage(node_id, body.method, body.note, body.palette)}

    @app.post("/api/nodes/{node_id}/cloud")
    def update_cloud(node_id: str, body: CloudBody) -> dict:
        wt.update_cloud(node_id, body.note, body.palette)
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/discard")
    def discard(node_id: str) -> dict:
        wt.discard(node_id)
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/instantiate")
    def instantiate(node_id: str, body: OptionalPaletteBody) -> dict:
        session_id = jobs.run_claimed("instantiate", node_id, lambda: wt.instantiate(node_id, body.palette))
        return {"session_id": session_id}

    @app.post("/api/nodes/{node_id}/split")
    def split(node_id: str, body: SplitBody) -> dict:
        return {"node_ids": wt.split(node_id, [f.strip() for f in body.focuses if f.strip()])}

    @app.post("/api/nodes/{node_id}/palette")
    def set_palette(node_id: str, body: PaletteBody) -> dict:
        wt.set_palette(node_id, body.palette)
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/note")
    def set_note(node_id: str, body: NoteBody) -> dict:
        wt.set_note(node_id, body.note)
        return {"ok": True}

    @app.post("/api/groups")
    def group_siblings(body: GroupBody) -> dict:
        return {"group_id": wt.group_siblings(body.node_ids)}

    @app.post("/api/nodes/{node_id}/group_parent")
    def set_group_parent(node_id: str, body: GroupParentBody) -> dict:
        wt.set_group_parent(node_id, body.group_id)
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/ungroup")
    def ungroup(node_id: str) -> dict:
        wt.ungroup(node_id)
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/cluster")
    def move_to_cluster(node_id: str, body: ClusterMoveBody) -> dict:
        wt.move_to_cluster(node_id, body.cluster_id)
        return {"ok": True}

    @app.get("/api/nodes/{node_id}/open_command")
    def open_command(node_id: str) -> dict:
        return {"command": wt.open_command(node_id)}

    @app.post("/api/signals")
    def set_signal(body: SignalBody) -> dict:
        wt.set_signal(body.name, body.enabled)
        return {"ok": True}

    @app.get("/api/clusters/proposals")
    def propose_clusters() -> list[dict]:
        return wt.propose_clusters()

    @app.post("/api/clusters/accept")
    def accept_proposals() -> dict:
        return {"cluster_ids": wt.accept_proposals()}

    @app.post("/api/clusters")
    def create_cluster(body: ClusterBody) -> dict:
        return {"cluster_id": wt.create_cluster(body.project, body.name, body.members)}

    @app.post("/api/clusters/{cluster_id}/rename")
    def rename_cluster(cluster_id: str, body: NameBody) -> dict:
        wt.rename_cluster(cluster_id, body.name)
        return {"ok": True}

    @app.post("/api/clusters/{cluster_id}/dissolve")
    def dissolve_cluster(cluster_id: str) -> dict:
        wt.dissolve_cluster(cluster_id)
        return {"ok": True}

    @app.post("/api/clusters/{cluster_id}/model_name")
    def model_cluster_name(cluster_id: str) -> dict:
        name = jobs.run_claimed("model_name", cluster_id, lambda: wt.model_cluster_name(cluster_id))
        return {"name": name}

    @app.post("/api/pull")
    def pull(body: PullBody) -> dict:
        return wt.pull(body.source, body.target, body.level)

    @app.post("/api/reviews")
    def start_review(body: ReviewBody) -> dict:
        if body.include not in ("summary", "none"):
            raise core.CoreError("include must be 'summary' or 'none'")
        review_id = wt.start_review(body.target, body.problem, body.reviewer, body.include)
        jobs.start_review(review_id)
        return {"review_id": review_id}

    @app.post("/api/reviews/{review_id}/run")
    def rerun_review(review_id: str) -> dict:
        if not any(r["id"] == review_id for r in wt.store.load()["reviews"]):
            raise core.CoreError(f"unknown review {review_id}")
        jobs.start_review(review_id)
        return {"review_id": review_id}

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: str) -> dict:
        review = next((r for r in wt.store.load()["reviews"] if r["id"] == review_id), None)
        if not review:
            raise core.CoreError(f"unknown review {review_id}")
        return dict(review, running=review_id in jobs.busy()["reviews"])

    @app.get("/api/reviews/{review_id}/prompt")
    def review_prompt(review_id: str) -> dict:
        return {"prompt": wt.review_prompt(review_id)}

    app.mount("/static", staticfiles.StaticFiles(directory=STATIC_DIR), name="static")
    return app


def serve(port: int, host: str = "127.0.0.1") -> None:
    """Serve the web GUI; requests must still address it as localhost."""
    print(f"Web Tree: http://127.0.0.1:{port}/")
    uvicorn.run(create_app(core.Core()), host=host, port=port, log_level="warning")
