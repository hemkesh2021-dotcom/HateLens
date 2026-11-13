from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import sqlite3
import time
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr, StringConstraints, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hatelens.config import Settings
from hatelens.evaluation import probe_audit
from hatelens.imports import ImportProblem, preview
from hatelens.model import HateLensModel
from hatelens.storage import Store
from hatelens.social import FetchProblem, fetch_preview, parse_social_url

Label = Literal["hate", "offensive", "neither"]
SocialSource = Literal["YouTube", "X"]
CommentText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]


class AnalysisInput(BaseModel):
    text: CommentText


class BatchInput(BaseModel):
    comments: list[CommentText] = Field(min_length=1, max_length=50)


class ImportPreviewInput(BaseModel):
    content: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    format: Literal["auto", "youtube", "x", "lines", "csv", "json"] = "auto"
    source: SocialSource = "YouTube"
    filename: str = Field(default="", max_length=255)
    column: str | None = Field(default=None, max_length=500)


class ImportLinkInput(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    source: SocialSource = "YouTube"
    limit: int = Field(default=50, ge=1, le=500)
    sort: Literal["top", "new"] = "top"
    include_replies: bool = False
    token: SecretStr = SecretStr("")


class ImportedComment(BaseModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    text: CommentText
    author: str = Field(default="", max_length=500)
    posted_at: str = Field(default="", max_length=500)
    likes: str = Field(default="", max_length=500)
    replies: str = Field(default="", max_length=500)
    original_id: str = Field(default="", max_length=500)
    parent_id: str = Field(default="", max_length=500)
    conversation_id: str = Field(default="", max_length=500)


class ImportAnalyzeInput(BaseModel):
    session_id: UUID
    source: SocialSource = "YouTube"
    source_url: str = Field(default="", max_length=2048)
    comments: list[ImportedComment] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_rows(self):
        if len({row.id for row in self.comments}) != len(self.comments):
            raise ValueError("Each imported comment needs a unique preview row ID.")
        if self.source_url:
            target = parse_social_url(self.source_url)
            if target["source"] != self.source:
                raise ValueError("The source link must match the selected platform.")
            self.source_url = target["url"]
        return self


class ModerationInput(BaseModel):
    action: Literal["approved", "hidden", "review", "unresolved"]


class FeedbackInput(BaseModel):
    kind: Literal["confirm", "correct", "context"]
    proposed_label: Label | None = None
    reason: Literal["agreement", "wrong_category", "quotation", "sarcasm", "opposing_hate", "missing_context", "other"] = "wrong_category"
    note: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def correction_has_label(self):
        if self.kind == "correct" and self.proposed_label is None:
            raise ValueError("Choose a label for a correction.")
        return self


class ReviewInput(BaseModel):
    status: Literal["accepted", "rejected"]
    reviewed_label: Label | None = None
    note: str = Field(default="", max_length=600)

    @model_validator(mode="after")
    def acceptance_has_label(self):
        if self.status == "accepted" and self.reviewed_label is None:
            raise ValueError("An accepted correction requires an adjudicated label.")
        return self


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(settings.database_path)
        app.state.model = None
        app.state.model_error = None
        if settings.model_path.is_file():
            try:
                app.state.model = HateLensModel.load(settings.model_path)
            except Exception:
                logging.exception("Could not load the locally trained HateLens model")
                app.state.model_error = "The model could not be loaded. Retrain it with the locked dependencies."
        yield

    app = FastAPI(title="HateLens", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-origin changes are not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def model_required():
        if app.state.model is None:
            raise HTTPException(503, app.state.model_error or "Train the model first: python -m hatelens.train --download --compare")
        return app.state.model

    @app.get("/api/status")
    def status():
        return {"ready": app.state.model is not None, "model": app.state.model.metadata if app.state.model else None,
                "error": app.state.model_error, "summary": app.state.store.summary()}

    @app.post("/api/analyze")
    def analyze(body: AnalysisInput):
        start = time.perf_counter()
        result = model_required().predict(body.text)
        result["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
        return app.state.store.save_prediction(result, "Manual")

    @app.post("/api/analyze/batch")
    def analyze_batch(body: BatchInput):
        model = model_required()
        results = [app.state.store.save_prediction(model.predict(text), "Batch") for text in body.comments]
        return {"items": results, "total": len(results)}

    @app.get("/api/comments")
    def comments(label: Label | None = None, review_only: bool = False, q: str = Query(default="", max_length=300),
                 limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0),
                 source: Literal["Manual", "Batch", "YouTube", "X"] | None = None):
        return app.state.store.list_predictions(label, review_only, q, limit, offset, source)

    @app.post("/api/import/preview")
    def import_preview(body: ImportPreviewInput):
        try:
            result = preview(body.content, body.format, body.filename, body.column, body.source)
        except ImportProblem as error:
            raise HTTPException(422, str(error)) from None
        return {**result, "session_id": str(uuid4())}

    @app.get("/api/import/providers")
    def import_providers():
        return {"youtube": {"available": True, "token_required": False},
                "x": {"token_configured": bool(os.environ.get("X_BEARER_TOKEN", "").strip()),
                      "scope": "Conversation replies from the last 7 days"}}

    @app.post("/api/import/link")
    def import_link(body: ImportLinkInput):
        try:
            result = fetch_preview(body.url, body.source, body.limit, body.sort, body.include_replies,
                                   body.token.get_secret_value())
        except FetchProblem as error:
            raise HTTPException(error.status, str(error)) from None
        except ImportProblem as error:
            raise HTTPException(422, str(error)) from None
        return {**result, "session_id": str(uuid4())}

    @app.post("/api/import/analyze")
    def import_analyze(body: ImportAnalyzeInput):
        model = model_required()
        results = []
        for row in body.comments:
            digest = hashlib.sha256(json.dumps(row.model_dump(exclude={"id"}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            prediction_id = uuid5(NAMESPACE_URL, f"hatelens:{body.session_id}:{body.source}:{body.source_url}:{row.id}:{digest}:{model.metadata['version']}").hex
            existing = app.state.store.get_prediction(prediction_id)
            if existing:
                results.append(existing)
                continue
            # Author, time, counts, and external IDs are provenance only, never model features.
            result = model.predict(row.text)
            result["import_metadata"] = {**row.model_dump(exclude={"text", "id"}), "row_id": row.id,
                                         "session_id": str(body.session_id), "source_url": body.source_url}
            results.append(app.state.store.save_prediction(result, body.source, prediction_id=prediction_id))
        return {"items": results, "total": len(results)}

    @app.get("/api/comments/{prediction_id}")
    def comment(prediction_id: str):
        result = app.state.store.get_prediction(prediction_id)
        if not result:
            raise HTTPException(404, "Comment not found.")
        return result

    @app.post("/api/comments/{prediction_id}/moderation")
    def moderate(prediction_id: str, body: ModerationInput):
        if not app.state.store.moderate(prediction_id, body.action):
            raise HTTPException(404, "Comment not found.")
        return {"action": body.action, "scope": "Saved in this local workspace only."}

    @app.post("/api/comments/{prediction_id}/feedback", status_code=201)
    def feedback(prediction_id: str, body: FeedbackInput):
        prediction = app.state.store.get_prediction(prediction_id)
        if not prediction:
            raise HTTPException(404, "Comment not found.")
        label = prediction["label"] if body.kind == "confirm" else body.proposed_label
        if body.kind == "correct" and label == prediction["label"]:
            raise HTTPException(422, "Choose a different label, or confirm the existing prediction.")
        try:
            return app.state.store.add_feedback(prediction_id, body.kind, label, body.reason, body.note.strip())
        except sqlite3.IntegrityError:
            raise HTTPException(409, "This comment already has feedback in the review workflow.") from None

    @app.get("/api/feedback")
    def feedback_list(status: Literal["pending", "accepted", "rejected"] | None = None,
                      limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        return app.state.store.feedback(status, limit, offset)

    @app.post("/api/feedback/{feedback_id}/review")
    def review(feedback_id: str, body: ReviewInput):
        result = app.state.store.review_feedback(feedback_id, body.status, body.reviewed_label, body.note.strip())
        if result == "missing":
            raise HTTPException(404, "Feedback not found.")
        if result == "reviewed":
            raise HTTPException(409, "This feedback has already been reviewed.")
        return {"status": body.status, "message": "Review saved. The active model is unchanged."}

    @app.get("/api/audit")
    def audit():
        return {"model_version": model_required().metadata["version"], **model_required().audit}

    @app.post("/api/audit/probes")
    def probes():
        model = model_required()
        return {"model_version": model.metadata["version"], "run_at": datetime.now(timezone.utc).isoformat(), **probe_audit(model)}

    @app.get("/api/export")
    def export():
        model = app.state.model
        return JSONResponse({"exported_at": datetime.now(timezone.utc).isoformat(),
                             "scope": "Model evaluation, bias audit, and workspace counts. Comment text is not included.",
                             "model": model.metadata if model else None, "audit": model.audit if model else None,
                             "workspace": app.state.store.summary()},
                            headers={"Content-Disposition": 'attachment; filename="hatelens-report.json"'})

    @app.get("/")
    def index():
        return FileResponse(settings.web_path / "index.html")

    app.mount("/static", StaticFiles(directory=settings.web_path, check_dir=False), name="static")
    return app


app = create_app()
