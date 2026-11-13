"""Bounded, read-only social imports. URLs are canonicalized before any network call."""

from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
from threading import BoundedSemaphore
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError

from hatelens.imports import ImportProblem, preview

FETCH_TIMEOUT = 55
FETCH_SLOTS = BoundedSemaphore(2)


class FetchProblem(ImportProblem):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def parse_social_url(value: str) -> dict:
    value = value.strip()
    if len(value) > 2048 or re.search(r"[\s\\\x00-\x1f]", value):
        raise FetchProblem("Paste a YouTube video link or an X post link.")
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError
        host = (parsed.hostname or "").lower()
    except ValueError:
        raise FetchProblem("Use an HTTPS YouTube video or X post link without a custom port or login details.") from None
    path = parsed.path.rstrip("/")
    video = None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if path == "/watch":
            values = parse_qs(parsed.query).get("v", [])
            video = values[0] if len(values) == 1 else None
        else:
            match = re.fullmatch(r"/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})", path)
            video = match[1] if match else None
    elif host in {"youtu.be", "www.youtu.be"}:
        video = path.removeprefix("/")
    if video and re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        return {"source": "YouTube", "id": video, "url": f"https://www.youtube.com/watch?v={video}"}
    if host in {"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
        match = re.fullmatch(r"/(?:[A-Za-z0-9_]{1,15}|i|i/web)/status/([0-9]{1,20})(?:/(?:photo|video)/[0-9]+)?", path)
        if match:
            return {"source": "X", "id": match[1], "url": f"https://x.com/i/status/{match[1]}"}
    raise FetchProblem("Use a YouTube watch, Shorts, or youtu.be link, or an x.com / twitter.com post link. Profile and playlist links are not supported.")


def fetch_preview(url: str, source: str, limit: int = 50, sort: str = "top",
                  include_replies: bool = False, token: str = "") -> dict:
    target = parse_social_url(url)
    if target["source"] != source:
        raise FetchProblem(f"This is a {target['source']} link. Select {target['source']} as the source.")
    if not 1 <= limit <= 500 or sort not in {"top", "new"}:
        raise FetchProblem("Choose 1–500 comments and a supported sort order.")
    token = (token or os.environ.get("X_BEARER_TOKEN", "")).strip() if source == "X" else ""
    if source == "X" and not token:
        raise FetchProblem("X link imports need an X API bearer token with post lookup and recent-search access. Enter it under “Connect your X API access” or configure X_BEARER_TOKEN on the server. Pasted comments and file uploads work without a token.")
    if token and (len(token) > 4096 or not re.fullmatch(r"[\x21-\x7e]+", token)):
        raise FetchProblem("The X bearer token has an invalid format. Use the token from your X developer app.")
    if not FETCH_SLOTS.acquire(blocking=False):
        raise FetchProblem("Two imports are already running. Wait for one to finish, then try again.", 429)
    try:
        request = {"target": target, "limit": limit, "sort": sort, "include_replies": include_replies, "token": token}
        # A child process gives the entire fetch a hard deadline, including pagination.
        # Credentials travel over stdin, never in a command line, URL, file, or log.
        process = subprocess.run([sys.executable, "-m", "hatelens.social_worker"], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=FETCH_TIMEOUT)
        if process.returncode or len(process.stdout) > 8 * 1024 * 1024:
            raise FetchProblem("The comment provider could not complete this import. Try a smaller limit or upload an export.", 502)
        result = json.loads(process.stdout)
        if not result.get("ok"):
            raise FetchProblem(result.get("message", "The comment import failed."), result.get("status", 502))
        data = result["data"]
        if data["comments"]:
            prepared = preview(json.dumps({"comments": data["comments"]}), "json")
        else:
            prepared = {"comments": [], "total": 0, "duplicates": 0, "too_long": 0, "removed_lines": 0,
                        "warnings": [], "needs_column": False}
        return {**prepared, "format": "link", "source": source, "source_url": target["url"],
                "title": data.get("title", ""), "fetched_at": datetime.now(timezone.utc).isoformat(),
                "requested_limit": limit, "scope": data["scope"],
                "warnings": prepared["warnings"] + data.get("warnings", [])}
    except subprocess.TimeoutExpired:
        raise FetchProblem("The import timed out after 55 seconds. Try fewer comments or upload a saved export.", 504) from None
    except (json.JSONDecodeError, KeyError, TypeError, OSError):
        raise FetchProblem("The provider returned an unreadable response. Try again or upload a comment export.", 502) from None
    finally:
        FETCH_SLOTS.release()


class QuietLog:
    def __init__(self):
        self.comment_warning = False

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        self.comment_warning |= "comment" in str(message).lower()

    def error(self, message):
        pass


def fetch_youtube(target: dict, limit: int, sort: str, include_replies: bool) -> dict:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    logger = QuietLog()
    options = {"skip_download": True, "getcomments": True, "noplaylist": True, "quiet": True,
               "logger": logger, "cachedir": False, "ignore_no_formats_error": True,
               "socket_timeout": 12, "retries": 1, "extractor_retries": 1,
               "extractor_args": {"youtube": {
                   "max_comments": [str(limit), str(limit), str(limit if include_replies else 0),
                                    str(limit if include_replies else 0), "all" if include_replies else "1"],
                   "comment_sort": [sort], "player_client": ["web"], "player_skip": ["js"],
                   "skip": ["hls", "dash", "translated_subs"], "fetch_pot": ["never"],
               }}}
    # Only public access: no browser cookies, login, downloaded video, or bypass fallback.
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(target["url"], download=False)
            if info:
                ydl.post_extract(info)
    except DownloadError as error:
        message = str(error).lower()
        if "disabled" in message and "comment" in message:
            raise FetchProblem("Comments are disabled for this video. Paste or upload comments from another video.") from None
        if any(word in message for word in ("sign in", "bot", "private", "age-restricted", "unavailable", "not available", "removed")):
            raise FetchProblem("YouTube did not make this video's comments available to public access. Open the video and paste visible comments, or upload an export.") from None
        raise FetchProblem("YouTube could not return comments. Try again with a smaller limit, or paste/upload the comments.", 502) from None
    if not info:
        raise FetchProblem("YouTube returned no video details. Check the video link.", 502)
    comments = info.get("comments") or []
    rows = []
    for comment in comments[:limit]:
        if not isinstance(comment.get("text"), str) or not comment["text"].strip():
            continue
        rows.append({"text": comment["text"], "author": comment.get("author") or "",
                     "posted_at": comment.get("_time_text") or "", "likes": str(comment.get("like_count") or 0),
                     "original_id": comment.get("id") or "", "parent_id": comment.get("parent") or ""})
    scope = "Top-level comments and available replies" if include_replies else "Top-level comments only"
    warnings = [f"{scope}, sorted by {'top comments' if sort == 'top' else 'newest first'}. Up to {limit} comments requested; this is a sample, not a complete or representative conversation."]
    if logger.comment_warning:
        warnings.append("YouTube reported a comment retrieval warning. This preview may be incomplete.")
    if not rows:
        warnings.append("No public comments were returned. Comments may be disabled, unavailable, or not yet posted.")
    return {"comments": rows, "title": info.get("title") or target["id"], "scope": scope, "warnings": warnings}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def x_request(path: str, params: dict, token: str) -> dict:
    request = Request("https://api.x.com/2/" + path + "?" + urlencode(params),
                      headers={"Authorization": "Bearer " + token, "Accept": "application/json", "User-Agent": "HateLens/0.1"})
    try:
        # Never forward a bearer token to a redirect destination.
        with build_opener(NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise FetchProblem("X returned too much data. Try a smaller comment limit.", 502)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except HTTPError as error:
        # X's current reference uses post.fields; older API deployments use tweet.fields.
        # Retry only a rejected field schema, never authentication or usage-limit errors.
        if error.code == 400 and "post.fields" in params:
            legacy = {key: value for key, value in params.items() if key != "post.fields"}
            legacy["tweet.fields"] = params["post.fields"].replace("note_post", "note_tweet")
            return x_request(path, legacy, token)
        messages = {401: "X did not accept the bearer token. Check the token in your X developer app.",
                    402: "X API credits are required for this request. Check your developer account, or paste/upload comments.",
                    403: "X denied access. Check your app's post lookup and recent-search access, or paste/upload comments.",
                    404: "X could not find this post. It may have been deleted or be unavailable to this app.",
                    429: "X's rate or usage limit was reached. Try later, or paste/upload comments."}
        raise FetchProblem(messages.get(error.code, "X could not complete the request. Check API access or upload an export."),
                           429 if error.code == 429 else 422 if error.code in messages else 502) from None
    except (URLError, TimeoutError, ValueError):
        raise FetchProblem("Could not read a response from X. Try again or upload an export.", 502) from None


def fetch_x(target: dict, limit: int, token: str) -> dict:
    lookup = x_request("tweets/" + target["id"], {"post.fields": "conversation_id"}, token)
    post = lookup.get("data") or {}
    conversation = post.get("conversation_id")
    if post.get("id") and not conversation:
        lookup = x_request("tweets/" + target["id"], {"tweet.fields": "conversation_id"}, token)
        conversation = (lookup.get("data") or {}).get("conversation_id")
    if not isinstance(conversation, str) or not re.fullmatch(r"[0-9]{1,20}", conversation):
        raise FetchProblem("X could not resolve the conversation. The post may be unavailable to this app.")
    rows, seen, seen_pages, warnings = [], set(), set(), []
    next_token = None
    for _ in range(10):
        params = {"query": f"conversation_id:{conversation} is:reply", "max_results": min(100, max(10, limit - len(rows))),
                  "sort_order": "recency", "post.fields": "id,text,created_at,conversation_id,public_metrics,note_post",
                  "expansions": "author_id", "user.fields": "username"}
        if next_token:
            params["next_token"] = next_token
        try:
            data = x_request("tweets/search/recent", params, token)
        except FetchProblem:
            if not rows:
                raise
            warnings.append("X stopped returning pages before the requested limit. These are only the replies retrieved so far.")
            break
        if data.get("errors"):
            if not data.get("data") and not rows:
                raise FetchProblem("X reported a search error. Check API access, or paste/upload the conversation.")
            warnings.append("X reported a partial response. Some replies or author details may be missing.")
        users = {user["id"]: user.get("username", "") for user in data.get("includes", {}).get("users", [])}
        for item in data.get("data", []):
            identity = str(item.get("id", ""))
            # Also accept the legacy note_tweet field in supplied/API data.
            note = item.get("note_post") or item.get("note_tweet") or {}
            text = note.get("text") or item.get("text")
            if not identity or identity in seen or identity == conversation or not isinstance(text, str) or not text.strip():
                continue
            seen.add(identity)
            metrics = item.get("public_metrics") or {}
            username = users.get(item.get("author_id")) or item.get("username") or ""
            rows.append({"text": text, "author": "@" + username if username else "", "posted_at": item.get("created_at") or "",
                         "likes": str(metrics.get("like_count", "")), "replies": str(metrics.get("reply_count", "")),
                         "original_id": identity, "conversation_id": conversation})
            if len(rows) >= limit:
                break
        next_token = data.get("meta", {}).get("next_token")
        if len(rows) >= limit or not next_token or next_token in seen_pages:
            break
        seen_pages.add(next_token)
    scope = "Conversation replies from the last 7 days, newest first"
    warnings.insert(0, f"{scope}. Includes replies anywhere in the conversation, not only direct replies to the linked post. The original post is excluded; this is not the full conversation history.")
    if len(rows) >= limit or next_token:
        warnings.append(f"Stopped after {len(rows)} replies. More replies may be available on X.")
    if not rows:
        warnings.append("No replies were returned in the recent-search window. This does not mean the conversation has no older replies.")
    return {"comments": rows, "title": f"X conversation {conversation}", "scope": scope, "warnings": warnings}
