import pytest
from fastapi.testclient import TestClient

from hatelens.app import create_app
from hatelens.config import Settings
from hatelens.storage import Store


def analyze(client, text="Everyone is welcome here"):
    response = client.post("/api/analyze", json={"text": text})
    assert response.status_code == 200
    return response.json()


def test_prediction_is_persistent_and_searchable(client):
    prediction = analyze(client, "Welcome <script>alert('x')</script> everyone")
    loaded = client.get(f"/api/comments/{prediction['id']}").json()
    assert loaded["text"] == prediction["text"]
    assert loaded["explanation"] == prediction["explanation"]
    assert client.get("/api/comments", params={"q": "<script>"}).json()["total"] == 1
    assert client.get("/api/comments", params={"q": "' OR 1=1 --"}).json()["total"] == 0
    assert client.get("/api/status").json()["summary"]["comments"]["total"] == 1


@pytest.mark.parametrize("text", ["", "   ", "a" * 3001, None, 123])
def test_invalid_comments_are_not_saved(client, text):
    assert client.post("/api/analyze", json={"text": text}).status_code == 422
    assert client.get("/api/status").json()["summary"]["comments"]["total"] == 0


def test_batch_validation_is_atomic_before_inference(client):
    assert client.post("/api/analyze/batch", json={"comments": ["hello", ""]}).status_code == 422
    assert client.post("/api/analyze/batch", json={"comments": ["hello"] * 51}).status_code == 422
    assert client.get("/api/comments").json()["total"] == 0
    response = client.post("/api/analyze/batch", json={"comments": ["everyone is welcome here", "your argument is stupid"]})
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_feedback_requires_review_and_cannot_overwrite_a_review(client):
    prediction = analyze(client)
    correction = "hate" if prediction["label"] != "hate" else "neither"
    path = f"/api/comments/{prediction['id']}/feedback"
    submitted = client.post(path, json={"kind": "correct", "proposed_label": correction, "note": "Synthetic test"})
    assert submitted.status_code == 201
    record = submitted.json()
    assert record["status"] == "pending"
    assert client.post(path, json={"kind": "confirm"}).status_code == 409
    assert client.post(f"/api/feedback/{record['id']}/review", json={"status": "accepted"}).status_code == 422
    reviewed = client.post(f"/api/feedback/{record['id']}/review", json={"status": "accepted", "reviewed_label": correction})
    assert reviewed.status_code == 200
    assert client.post(f"/api/feedback/{record['id']}/review", json={"status": "rejected"}).status_code == 409
    accepted = client.get("/api/feedback?status=accepted").json()["items"]
    assert len(accepted) == 1 and accepted[0]["reviewed_label"] == correction
    assert analyze(client)["probabilities"] == prediction["probabilities"]
    assert client.get("/api/status").json()["model"]["version"] == prediction["model_version"]


def test_context_feedback_can_be_rejected_without_a_label(client):
    prediction = analyze(client)
    record = client.post(f"/api/comments/{prediction['id']}/feedback", json={"kind": "context", "reason": "missing_context"}).json()
    assert client.post(f"/api/feedback/{record['id']}/review", json={"status": "rejected"}).status_code == 200


def test_moderation_resolves_queue_without_changing_prediction(client):
    prediction = analyze(client, "你好 世界")
    assert client.get("/api/comments?review_only=true").json()["total"] == 1
    assert client.post(f"/api/comments/{prediction['id']}/moderation", json={"action": "approved"}).status_code == 200
    assert client.get("/api/comments?review_only=true").json()["total"] == 0
    assert client.get(f"/api/comments/{prediction['id']}").json()["label"] == prediction["label"]
    assert client.post(f"/api/comments/{prediction['id']}/moderation", json={"action": "review"}).status_code == 200
    assert client.get("/api/comments?review_only=true").json()["total"] == 1


def test_export_omits_user_comment_text(client):
    analyze(client, "Private user example phrase 424242")
    exported = client.get("/api/export")
    assert exported.status_code == 200
    assert "Private user example phrase 424242" not in exported.text
    assert exported.json()["workspace"]["comments"]["total"] == 1


def test_cross_origin_writes_and_invalid_host_are_blocked(client):
    assert client.post("/api/analyze", headers={"Origin": "https://example.com"}, json={"text": "hello"}).status_code == 403
    assert client.get("/api/status", headers={"Host": "attacker.example"}).status_code == 400
    assert client.post("/api/analyze", headers={"Origin": "http://testserver"}, json={"text": "hello"}).status_code == 200


def test_missing_model_is_recoverable(tmp_path):
    app = create_app(Settings(model_path=tmp_path / "missing.joblib", database_path=tmp_path / "records.sqlite3"))
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/status").json()["ready"] is False
        assert client.post("/api/analyze", json={"text": "hello"}).status_code == 503
        assert client.get("/api/status").json()["summary"]["comments"]["total"] == 0


def test_sqlite_records_survive_store_restart(tmp_path, model):
    path = tmp_path / "persistent.sqlite3"
    first = Store(path)
    result = first.save_prediction(model.predict("welcome here"), "Manual")
    second = Store(path)
    assert second.get_prediction(result["id"])["text"] == "welcome here"


def test_api_static_files_and_diagnostic_run(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/audit").status_code == 200
    probes = client.post("/api/audit/probes", json={}).json()
    assert probes["total"] == 56
    assert "run_at" in probes
    assert client.get("/api/comments?label=unknown").status_code == 422
    assert client.get("/api/comments?offset=-1").status_code == 422
