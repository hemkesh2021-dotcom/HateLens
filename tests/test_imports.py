import csv
import io
import json
from pathlib import Path
from uuid import uuid4

import pytest

from hatelens.imports import ImportProblem, MAX_BYTES, preview

FIXTURE = Path(__file__).parent / "fixtures" / "youtube_copy.txt"


def test_supplied_youtube_paste_extracts_all_23_comments_without_metadata():
    result = preview(FIXTURE.read_text())
    assert result["format"] == "youtube"
    assert result["total"] == 23
    assert result["removed_lines"] == 105
    assert result["duplicates"] == 0
    comments = result["comments"]
    assert comments[0]["text"] == "Everyone was talking about how good the Chinese models were that he had to try one"
    assert not comments[0].get("author")
    assert comments[0]["likes"] == "3.7K"
    assert comments[0]["replies"] == "28 replies"
    assert comments[1]["author"] == "@TheMR-777"
    assert comments[8]["text"] == "1 hour ago: 3rd affair reported 😂"
    assert comments[14]["posted_at"] == "8 hours ago (edited)"
    assert comments[16]["author"] == "@HaüüPaüü"
    assert comments[-1]["text"] == "this is the huang way to run a company"
    assert all("\\" not in row["text"] and "\nReply\n" not in row["text"] for row in comments)


def test_copy_with_real_newlines_produces_same_comments_as_escaped_copy():
    escaped = FIXTURE.read_text()
    actual = escaped.replace("\\\n", "\n")
    assert preview(escaped)["comments"] == preview(actual)["comments"]


def test_youtube_parser_preserves_paragraphs_mentions_and_numbers_in_comment_body():
    text = "@reader\n3 days ago\nFirst line with @somebody\n\n2026 was mentioned in this paragraph.\nSecond line.\n\n19\nReply\n2 replies"
    row = preview(text)["comments"][0]
    assert row["text"] == "First line with @somebody\n\n2026 was mentioned in this paragraph.\nSecond line."
    assert row["likes"] == "19"


@pytest.mark.parametrize("body", ["2026", "Reply", "8 hours ago", "@someone", "A path ending with \\"])
def test_numeric_or_metadata_like_comment_text_is_not_erased(body):
    row = preview(f"@author\n2 hours ago\n{body}\n\n5\nReply")["comments"][0]
    assert row["text"] == body


def test_plain_text_does_not_discard_metadata_like_lines():
    result = preview("Reply\n2026\n@someone\n8 hours ago", format="lines")
    assert [row["text"] for row in result["comments"]] == ["Reply", "2026", "@someone", "8 hours ago"]


def test_csv_preserves_commas_multiline_emoji_and_html_as_literal_original_text():
    text = "Hello, world! 👋\nA second line with <b>literal markup</b>."
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["author", "comment_text", "likeCount"])
    writer.writeheader()
    writer.writerow({"author": "@person", "comment_text": text, "likeCount": 100})
    result = preview(stream.getvalue(), filename="comments.csv")
    assert result["comments"][0]["text"] == text
    assert result["comments"][0]["author"] == "@person"
    assert result["comments"][0]["likes"] == "100"
    assert preview(stream.getvalue())["format"] == "csv"


def test_custom_csv_column_is_requested_then_used():
    content = "Username,Message,Rating\n@a,Hello there,5\n@b,,2\n"
    first = preview(content, filename="comments.csv")
    assert first["needs_column"] and first["comments"] == []
    second = preview(content, filename="comments.csv", column="Message")
    assert second["comments"][0]["text"] == "Hello there"
    assert second["skipped_empty"] == 1
    with pytest.raises(ImportProblem, match="not in the CSV"):
        preview(content, format="csv", column="missing")


def test_malformed_csv_and_duplicate_headers_are_reported():
    with pytest.raises(ImportProblem, match="more fields"):
        preview("text,author\nUnquoted, comma,@person", format="csv")
    with pytest.raises(ImportProblem, match="unique"):
        preview("text,text\none,two", format="csv")


def test_youtube_json_thread_extracts_top_comment_available_replies_and_provenance():
    document = {"items": [{"id": "thread-id", "snippet": {"totalReplyCount": 20,
        "topLevelComment": {"id": "top-id", "snippet": {"authorDisplayName": "@author", "textOriginal": "Original comment", "publishedAt": "2026-11-13T10:00:00Z", "likeCount": 4}}},
        "replies": {"comments": [{"id": "reply-id", "snippet": {"textDisplay": "A &amp; B<br>Next line <a href='https://example.com'>link</a>"}}]}}]}
    result = preview(json.dumps(document), filename="export.json")
    assert result["total"] == 2
    assert result["comments"][0]["original_id"] == "top-id"
    assert result["comments"][0]["replies"] == "20"
    assert result["comments"][1]["text"] == "A & B\nNext line link"
    assert "not included" in result["warnings"][0]


def test_downloaded_cleaned_json_can_be_reimported_without_text_or_metadata_loss():
    row = {"text": "Some text", "author": "@a", "posted_at": "2 hours ago", "likes": "3.7K", "replies": "28 replies", "original_id": "comment-id"}
    result = preview(json.dumps({"comments": [row]}))
    assert {key: result["comments"][0][key] for key in row} == row


def test_duplicates_and_overlong_comments_are_retained_and_flagged():
    result = preview(json.dumps(["Hello there", "HELLO   there", "x" * 3001]))
    assert result["total"] == 3
    assert result["duplicates"] == 1
    assert result["comments"][1]["duplicate_of"] == "row-1"
    assert result["too_long"] == 1
    assert len(result["comments"][2]["text"]) == 3001
    assert not result["comments"][2]["valid"]


def test_import_limits_do_not_silently_truncate():
    with pytest.raises(ImportProblem, match="500"):
        preview(json.dumps(["hello"] * 501))
    with pytest.raises(ImportProblem, match="2 MB"):
        preview("x" * (MAX_BYTES + 1))
    with pytest.raises(ImportProblem, match="Binary"):
        preview("abc\x00def")
    with pytest.raises(ImportProblem, match="not valid JSON"):
        preview("not json", format="json")


def test_preview_does_not_save_or_classify_comments(client):
    response = client.post("/api/import/preview", json={"content": FIXTURE.read_text()})
    assert response.status_code == 200
    assert response.json()["total"] == 23
    assert client.get("/api/comments").json()["total"] == 0


def test_import_analyzes_only_selected_text_saves_provenance_and_is_retry_safe(client):
    rows = [{"id": "row-1", "text": "Everyone is welcome here", "author": "@not_model_input", "likes": "999999"}]
    payload = {"session_id": str(uuid4()), "comments": rows}
    first = client.post("/api/import/analyze", json=payload)
    assert first.status_code == 200
    item = first.json()["items"][0]
    assert item["source"] == "YouTube"
    assert item["text"] == rows[0]["text"]
    assert item["import_metadata"]["author"] == "@not_model_input"
    second = client.post("/api/import/analyze", json=payload)
    assert second.json()["items"][0]["id"] == item["id"]
    assert client.get("/api/comments?source=YouTube").json()["total"] == 1
    manual = client.post("/api/analyze", json={"text": rows[0]["text"]}).json()
    assert manual["probabilities"] == item["probabilities"]
    assert manual["explanation"] == item["explanation"]
    assert client.get("/api/comments?source=Manual").json()["total"] == 1
    assert client.get("/api/comments?source=YouTube&label=" + item["label"]).json()["total"] == 1


def test_edited_import_is_a_new_prediction_and_previous_record_is_preserved(client):
    payload = {"session_id": str(uuid4()), "comments": [{"id": "row-1", "text": "Hello there"}]}
    first = client.post("/api/import/analyze", json=payload).json()["items"][0]
    payload["comments"][0]["text"] = "Hello there with more context"
    second = client.post("/api/import/analyze", json=payload).json()["items"][0]
    assert first["id"] != second["id"]
    assert client.get(f"/api/comments/{first['id']}").json()["text"] == "Hello there"


def test_invalid_import_batch_is_rejected_before_any_saves(client):
    row = {"id": "row-1", "text": "hello"}
    assert client.post("/api/import/analyze", json={"session_id": str(uuid4()), "comments": [row, row]}).status_code == 422
    assert client.post("/api/import/analyze", json={"session_id": str(uuid4()), "comments": [{**row, "text": "x" * 3001}]}).status_code == 422
    assert client.get("/api/comments").json()["total"] == 0
