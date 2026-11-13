"""Local, durable analysis and an explicit two-stage feedback workflow."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS predictions (
                    id TEXT PRIMARY KEY, text TEXT NOT NULL, label TEXT NOT NULL,
                    score REAL NOT NULL, needs_review INTEGER NOT NULL,
                    source TEXT NOT NULL, model_version TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    moderation TEXT NOT NULL DEFAULT 'unresolved'
                        CHECK (moderation IN ('unresolved','approved','hidden','review'))
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL UNIQUE REFERENCES predictions(id),
                    kind TEXT NOT NULL CHECK (kind IN ('confirm','correct','context')),
                    proposed_label TEXT, reason TEXT NOT NULL, note TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected')),
                    reviewed_label TEXT, reviewer_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, reviewed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS predictions_created ON predictions(created_at DESC);
                CREATE INDEX IF NOT EXISTS feedback_status ON feedback(status);
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save_prediction(self, prediction: dict, source: str, prediction_id: str | None = None) -> dict:
        prediction = {**prediction, "id": prediction_id or uuid4().hex, "created_at": timestamp(), "source": source,
                      "moderation": "unresolved", "feedback_status": None}
        with self.connect() as connection:
            inserted = connection.execute("""INSERT INTO predictions
                (id,text,label,score,needs_review,source,model_version,payload,created_at)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING""",
                (prediction["id"], prediction["text"], prediction["label"], prediction["score"],
                 int(prediction["needs_review"]), source, prediction["model_version"],
                 json.dumps(prediction), prediction["created_at"]))
        if inserted.rowcount == 0:
            return self.get_prediction(prediction["id"])
        return prediction

    @staticmethod
    def decode_prediction(row) -> dict:
        result = json.loads(row["payload"])
        result["moderation"] = row["moderation"]
        result["feedback_status"] = row["feedback_status"]
        return result

    def get_prediction(self, prediction_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("""SELECT p.*, f.status AS feedback_status FROM predictions p
                LEFT JOIN feedback f ON f.prediction_id=p.id WHERE p.id=?""", (prediction_id,)).fetchone()
        return self.decode_prediction(row) if row else None

    def list_predictions(self, label=None, review_only=False, query="", limit=25, offset=0, source=None) -> dict:
        clauses, values = [], []
        if label:
            clauses.append("p.label=?")
            values.append(label)
        if source:
            clauses.append("p.source=?")
            values.append(source)
        if review_only:
            clauses.append("(p.needs_review=1 OR p.moderation='review') AND p.moderation NOT IN ('approved','hidden')")
        if query:
            clauses.append("instr(lower(p.text), lower(?)) > 0")
            values.append(query)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM predictions p {where}", values).fetchone()[0]
            rows = connection.execute(f"""SELECT p.*, f.status AS feedback_status FROM predictions p
                LEFT JOIN feedback f ON f.prediction_id=p.id {where}
                ORDER BY p.created_at DESC, p.id DESC LIMIT ? OFFSET ?""", [*values, limit, offset]).fetchall()
        return {"items": [self.decode_prediction(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def moderate(self, prediction_id: str, action: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("UPDATE predictions SET moderation=? WHERE id=?", (action, prediction_id))
            return cursor.rowcount == 1

    def add_feedback(self, prediction_id: str, kind: str, proposed_label: str | None, reason: str, note: str) -> dict:
        record = {"id": uuid4().hex, "prediction_id": prediction_id, "kind": kind,
                  "proposed_label": proposed_label, "reason": reason, "note": note,
                  "status": "pending", "created_at": timestamp()}
        with self.connect() as connection:
            connection.execute("""INSERT INTO feedback
                (id,prediction_id,kind,proposed_label,reason,note,created_at)
                VALUES (:id,:prediction_id,:kind,:proposed_label,:reason,:note,:created_at)""", record)
        return record

    def feedback(self, status=None, limit=50, offset=0) -> dict:
        where = "WHERE f.status=?" if status else ""
        values = [status] if status else []
        with self.connect() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM feedback f {where}", values).fetchone()[0]
            rows = connection.execute(f"""SELECT f.*, p.text, p.label AS original_label, p.model_version
                FROM feedback f JOIN predictions p ON p.id=f.prediction_id {where}
                ORDER BY f.created_at DESC LIMIT ? OFFSET ?""", [*values, limit, offset]).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def review_feedback(self, feedback_id: str, status: str, label: str | None, note: str) -> str:
        with self.connect() as connection:
            existing = connection.execute("SELECT status FROM feedback WHERE id=?", (feedback_id,)).fetchone()
            if not existing:
                return "missing"
            if existing["status"] != "pending":
                return "reviewed"
            updated = connection.execute("""UPDATE feedback SET status=?, reviewed_label=?, reviewer_note=?, reviewed_at=?
                WHERE id=? AND status='pending'""", (status, label if status == "accepted" else None, note, timestamp(), feedback_id))
            if updated.rowcount != 1:
                return "reviewed"
        return "ok"

    def summary(self) -> dict:
        with self.connect() as connection:
            counts = dict(connection.execute("""SELECT COUNT(*) AS total,
                COALESCE(SUM(label='hate'),0) AS hate,
                COALESCE(SUM(label='offensive'),0) AS offensive,
                COALESCE(SUM(label='neither'),0) AS neither,
                COALESCE(SUM((needs_review=1 OR moderation='review') AND moderation NOT IN ('approved','hidden')),0) AS review
                FROM predictions""").fetchone())
            feedback = dict(connection.execute("""SELECT COUNT(*) AS total,
                COALESCE(SUM(status='pending'),0) AS pending,
                COALESCE(SUM(status='accepted'),0) AS accepted,
                COALESCE(SUM(status='rejected'),0) AS rejected FROM feedback""").fetchone())
        return {"comments": counts, "feedback": feedback}
