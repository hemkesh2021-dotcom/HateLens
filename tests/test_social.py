import json
import subprocess
from types import SimpleNamespace
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from hatelens import social
from hatelens.imports import preview
from hatelens.social import FetchProblem, fetch_preview, fetch_x, parse_social_url, x_request

VIDEO = "SOwUWPtXQ9I"


@pytest.mark.parametrize("url", [f"https://www.youtube.com/watch?v={VIDEO}&t=10", f"youtu.be/{VIDEO}?si=abc",
                               f"https://m.youtube.com/shorts/{VIDEO}", f"https://youtube.com/live/{VIDEO}"])
def test_youtube_urls_are_canonicalized(url):
    assert parse_social_url(url) == {"source": "YouTube", "id": VIDEO, "url": f"https://www.youtube.com/watch?v={VIDEO}"}


@pytest.mark.parametrize("url", ["https://x.com/test/status/12345?s=20", "https://twitter.com/test/status/12345",
                               "https://mobile.twitter.com/test/status/12345", "https://x.com/i/web/status/12345/photo/1"])
def test_x_urls_are_canonicalized(url):
    assert parse_social_url(url) == {"source": "X", "id": "12345", "url": "https://x.com/i/status/12345"}


@pytest.mark.parametrize("url", ["https://127.0.0.1/status/123", "https://youtube.com.evil.test/watch?v=" + VIDEO,
                               "https://youtube.com@evil.test/watch?v=" + VIDEO, "http://youtube.com/watch?v=" + VIDEO,
                               "https://youtube.com:123/watch?v=" + VIDEO, "https://x.com/username", "file:///etc/passwd",
                               "https://x.com/u/status/no", "https://youtube.com/watch?v=too-short",
                               "https://x.com/u/status/123\nheader:value", "https://x.com\\@evil.test/u/status/123"])
def test_untrusted_or_nonpost_urls_are_rejected_before_network(url):
    with pytest.raises(FetchProblem):
        parse_social_url(url)


def test_x_json_export_preserves_full_text_unicode_metadata_and_user_expansions():
    data = {"data": [{"id": "123", "text": "Shortened…", "note_post": {"text": "Full text, with @mention\nNext line 👋"},
                      "author_id": "u1", "created_at": "2026-11-13T10:00:00Z", "conversation_id": "100",
                      "public_metrics": {"like_count": 42, "reply_count": 3}}],
            "includes": {"users": [{"id": "u1", "username": "reader"}]}}
    row = preview(json.dumps(data), source="X")["comments"][0]
    assert row["text"] == "Full text, with @mention\nNext line 👋"
    assert (row["author"], row["likes"], row["replies"], row["original_id"], row["conversation_id"]) == ("@reader", "42", "3", "123", "100")
    archive = [{"tweet": {"full_text": "Archived text", "id_str": "456", "favorite_count": "8"}}]
    archived = preview(json.dumps(archive), source="X")["comments"][0]
    assert (archived["text"], archived["original_id"], archived["likes"]) == ("Archived text", "456", "8")


def test_x_copy_separates_headers_and_preserves_ambiguous_content_for_review():
    data = "@reader · 2h\nFirst paragraph\n\nMention @friend and number 2026\n10\n@other\n·\nNov 12, 2026\nReplying to @reader\nAnother comment"
    result = preview(data, source="X")
    assert result["format"] == "x" and result["total"] == 2
    assert result["comments"][0]["text"] == "First paragraph\n\nMention @friend and number 2026\n10"
    assert result["comments"][1]["author"] == "@other"
    assert result["comments"][1]["text"].startswith("Replying to @reader")
    assert "review and edit" in result["warnings"][0]


def test_x_recent_search_paginates_deduplicates_and_maps_full_text(monkeypatch):
    calls = []
    pages = iter([
        {"data": {"id": "222", "conversation_id": "111"}},
        {"data": [{"id": "111", "text": "Root excluded"}, {"id": "301", "text": "First", "author_id": "7", "public_metrics": {"like_count": 5}}],
         "includes": {"users": [{"id": "7", "username": "person"}]}, "meta": {"next_token": "page-2"}},
        {"data": [{"id": "301", "text": "Duplicate"}, {"id": "302", "text": "Short…", "note_tweet": {"text": "Full long text"}}], "meta": {}}
    ])
    def request(path, params, token):
        calls.append((path, params, token))
        return next(pages)
    monkeypatch.setattr(social, "x_request", request)
    result = fetch_x(parse_social_url("https://x.com/u/status/222"), 20, "test-token")
    assert [row["original_id"] for row in result["comments"]] == ["301", "302"]
    assert result["comments"][0]["author"] == "@person"
    assert result["comments"][1]["text"] == "Full long text"
    assert calls[1][1]["query"] == "conversation_id:111 is:reply"
    assert calls[2][1]["next_token"] == "page-2"
    assert "last 7 days" in result["scope"]


def test_x_page_failure_returns_honest_partial_preview(monkeypatch):
    responses = iter([{"data": {"id": "111", "conversation_id": "111"}},
                      {"data": [{"id": "222", "text": "A reply"}], "meta": {"next_token": "more"}}])
    def request(*args):
        try:
            return next(responses)
        except StopIteration:
            raise FetchProblem("Rate limited", 429)
    monkeypatch.setattr(social, "x_request", request)
    result = fetch_x(parse_social_url("https://x.com/u/status/111"), 10, "test-token")
    assert len(result["comments"]) == 1
    assert any("stopped returning" in warning for warning in result["warnings"])


@pytest.mark.parametrize("code, expected", [(401, "token"), (402, "credits"), (403, "denied"), (404, "find"), (429, "limit")])
def test_x_errors_never_echo_provider_body_or_credentials(monkeypatch, code, expected):
    class Opener:
        def open(self, request, timeout):
            assert request.full_url.startswith("https://api.x.com/2/")
            assert "secret" not in request.full_url
            raise HTTPError(request.full_url, code, "sensitive provider diagnostic", {}, None)
    monkeypatch.setattr(social, "build_opener", lambda *args: Opener())
    with pytest.raises(FetchProblem, match=expected) as error:
        x_request("tweets/111", {}, "secret")
    assert "secret" not in str(error.value) and "sensitive" not in str(error.value)


def test_x_missing_token_and_platform_mismatch_never_start_a_worker(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("No network worker should run")
    monkeypatch.setattr(social.subprocess, "run", forbidden)
    with pytest.raises(FetchProblem, match="bearer token"):
        fetch_preview("https://x.com/u/status/111", "X")
    with pytest.raises(FetchProblem, match="Select X"):
        fetch_preview("https://x.com/u/status/111", "YouTube")


def test_x_supports_legacy_field_names_after_a_bad_request(monkeypatch):
    urls = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return b'{"data": {"id": "111", "conversation_id": "111"}}'
    class Opener:
        def open(self, request, timeout):
            urls.append(request.full_url)
            if len(urls) == 1:
                raise HTTPError(request.full_url, 400, "Unrecognized parameter", {}, None)
            return Response()
    monkeypatch.setattr(social, "build_opener", lambda *args: Opener())
    assert x_request("tweets/111", {"post.fields": "conversation_id,note_post"}, "secret")["data"]["conversation_id"] == "111"
    assert "tweet.fields=conversation_id%2Cnote_tweet" in urls[1]
    assert all("secret" not in url for url in urls)


def test_x_redirect_is_not_followed():
    assert social.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.example/") is None


def test_fetch_worker_sends_secret_via_stdin_only_and_preview_does_not_save(monkeypatch, client):
    def run(command, **kwargs):
        assert "secret-test" not in " ".join(command)
        request = json.loads(kwargs["input"])
        assert request["token"] == "secret-test"
        assert request["target"]["url"] == "https://x.com/i/status/111"
        assert kwargs["timeout"] == 55
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "data": {
            "comments": [{"text": "A fetched reply", "author": "@a", "original_id": "222"}],
            "scope": "Recent replies", "warnings": [], "title": "Test conversation"}}))
    monkeypatch.setattr(social.subprocess, "run", run)
    response = client.post("/api/import/link", json={"url": "https://x.com/u/status/111?s=2", "source": "X", "token": "secret-test"})
    assert response.status_code == 200
    assert response.json()["total"] == 1 and response.json()["source"] == "X"
    assert "secret-test" not in response.text
    assert client.get("/api/comments").json()["total"] == 0


def test_worker_timeout_is_reported_and_slot_is_released(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 55)
    monkeypatch.setattr(social.subprocess, "run", run)
    for _ in range(3):
        with pytest.raises(FetchProblem, match="timed out") as error:
            fetch_preview(f"https://youtu.be/{VIDEO}", "YouTube")
        assert error.value.status == 504


def test_source_filter_and_provenance_are_saved_without_changing_model_inputs(client):
    payload = {"session_id": str(uuid4()), "source": "X", "source_url": "https://twitter.com/u/status/111?s=1",
               "comments": [{"id": "row-1", "text": "Everyone is welcome here", "author": "@a", "original_id": "222"}]}
    result = client.post("/api/import/analyze", json=payload).json()["items"][0]
    assert result["source"] == "X"
    assert result["import_metadata"]["source_url"] == "https://x.com/i/status/111"
    assert client.get("/api/comments?source=X").json()["total"] == 1
    assert client.get("/api/comments?source=YouTube").json()["total"] == 0
    assert client.post("/api/import/analyze", json=payload).json()["items"][0]["id"] == result["id"]
    original = client.post("/api/analyze", json={"text": payload["comments"][0]["text"]}).json()
    assert original["probabilities"] == result["probabilities"]
    payload["source_url"] = "https://evil.test/status/111"
    assert client.post("/api/import/analyze", json=payload).status_code == 422


def test_link_endpoint_limits_and_token_status(client, monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "not-a-real-secret")
    status = client.get("/api/import/providers")
    assert status.json()["x"]["token_configured"]
    assert "not-a-real-secret" not in status.text
    for limit in [0, 501]:
        assert client.post("/api/import/link", json={"url": f"https://youtu.be/{VIDEO}", "limit": limit}).status_code == 422
