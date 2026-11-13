"""Conservative, deterministic comment extraction. No model or network access."""

import csv
from html.parser import HTMLParser
import io
import json
import re
import unicodedata

MAX_BYTES = 2 * 1024 * 1024
MAX_COMMENTS = 500
MAX_COMMENT_LENGTH = 3000
HANDLE = re.compile(r"^@[\w.\-·]+$", re.UNICODE)
TIME = re.compile(r"^(?:\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago|just now|yesterday)(?:\s*\(edited\))?$", re.I)
COUNT = re.compile(r"^\d+(?:[,.]\d+)*(?:\s*[KMB])?$", re.I)
REPLIES = re.compile(r"^(?:(?:view(?: all)?|show|hide)\s+)?(?:\d+(?:[,.]\d+)*\s*)?repl(?:y|ies)$", re.I)
PREAMBLE = re.compile(r"^(?:\d[\d,.KMB ]* comments?|comments|sort by|top comments|newest first|add a comment(?:\.{3}|…)?|cancel)$", re.I)
TEXT_FIELDS = ("textoriginal", "fulltext", "commenttext", "comment", "text", "textdisplay", "content", "body", "comments", "tweet")
X_TIME = r"(?:\d+\s*[smhd]|\d+\s+(?:seconds?|minutes?|hours?|days?)\s+ago|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?)"
X_HEADER = re.compile(rf"^(@[A-Za-z0-9_]{{1,15}})\s*[·•]\s*({X_TIME})$", re.I)


class ImportProblem(ValueError):
    pass


def field_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div"} and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def visible_text(value: str) -> str:
    parser = VisibleText()
    parser.feed(value)
    return "".join(parser.parts).strip()


def metadata(value) -> str:
    return str(value).strip()[:500] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def record_from_object(record: dict, column: str | None = None) -> dict | None:
    columns = {field_key(str(key)): key for key in record}
    chosen = column or next((columns[key] for key in TEXT_FIELDS if key in columns
                             and isinstance(record[columns[key]], str) and record[columns[key]].strip()), None)
    value = record.get(chosen) if chosen is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = visible_text(value) if field_key(str(chosen)) == "textdisplay" else value.strip()
    if not text:
        return None

    def pick(*keys):
        return next((metadata(record[columns[key]]) for key in keys if key in columns), "")

    return {"text": text, "author": pick("authordisplayname", "author", "username", "handle", "user"),
            "posted_at": pick("publishedat", "postedat", "createdat", "timestamp", "date", "time"),
            "likes": pick("likecount", "favoritecount", "likes"), "replies": pick("replycount", "replies", "totalreplycount"),
            "original_id": pick("commentid", "originalid", "idstr", "id"),
            "parent_id": pick("parentid", "inreplytostatusidstr"), "conversation_id": pick("conversationid")}


def copy_lines(content: str) -> list[str]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # Some rich-text clipboard exports escape every line break as a backslash.
    escaped = sum(line.strip() == "\\" for line in lines) >= 2
    return [(line.rstrip().removesuffix("\\") if escaped else line).strip() for line in lines]


def parse_youtube_copy(content: str) -> tuple[list[dict], dict]:
    lines = copy_lines(content)
    rows, block = [], []
    current = {}
    removed = 0
    shortened = 0

    def flush():
        nonlocal block, current, removed, shortened
        # Preserve comment paragraphs. Only peel recognizable controls from the end.
        body = list(block)
        while body and not body[-1]:
            body.pop()
        meta = dict(current)
        while len([line for line in body if line]) > 1:
            last = body[-1]
            if last.lower() == "reply":
                body.pop()
                removed += 1
                while body and not body[-1]:
                    body.pop()
                if len([line for line in body if line]) > 1 and COUNT.fullmatch(body[-1]):
                    meta["likes"] = body.pop()
                    removed += 1
            elif REPLIES.fullmatch(last):
                meta["replies"] = body.pop()
                removed += 1
            elif last.lower() in {"read more", "show less", "translate to english", "translate to english (auto-generated)"}:
                body.pop()
                removed += 1
                shortened += int(last.lower() == "read more")
            else:
                break
            while body and not body[-1]:
                body.pop()
        # A preamble can precede the first visible comment, which may lack its author.
        if not current:
            while body and (not body[0] or PREAMBLE.fullmatch(body[0])):
                removed += bool(body.pop(0))
        text = "\n".join(body).strip()
        if text:
            rows.append({"text": text, **meta})
        block = []
        current = {}

    index = 0
    while index < len(lines):
        line = lines[index]
        following = index + 1
        while following < len(lines) and not lines[following]:
            following += 1
        if HANDLE.fullmatch(line) and following < len(lines) and TIME.fullmatch(lines[following]):
            flush()
            current = {"author": line, "posted_at": lines[following]}
            removed += 2
            index = following + 1
            continue
        block.append(line)
        index += 1
    flush()
    warnings = ["Copy/paste extraction is a best-effort preview. Check comment boundaries before analysis.",
                "Only visible pasted comments are included. Reply counts do not include the text of unexpanded replies."]
    if shortened:
        warnings.append(f"{shortened} “Read more” controls were removed; expand those comments on YouTube if you need their full text.")
    return rows, {"removed_lines": removed, "warnings": warnings}


def parse_csv(content: str, column: str | None) -> tuple[list[dict], dict]:
    try:
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content, newline=""), dialect=dialect, strict=True)
        headers = reader.fieldnames or []
        if not headers or len(set(headers)) != len(headers) or any(not key.strip() for key in headers):
            raise ImportProblem("The CSV needs unique, nonempty column headers.")
        if len(headers) > 100:
            raise ImportProblem("Use a CSV with at most 100 columns.")
        columns = {field_key(key): key for key in headers}
        chosen = column or next((columns[key] for key in TEXT_FIELDS if key in columns), None)
        if chosen and chosen not in headers:
            raise ImportProblem("That comment column is not in the CSV. Choose one of the listed columns.")
        if not chosen:
            return [], {"columns": headers, "selected_column": None, "needs_column": True,
                        "warnings": ["Choose the CSV column containing comment text, then preview again."]}
        rows, skipped = [], []
        for index, row in enumerate(reader, start=2):
            if None in row:
                raise ImportProblem(f"CSV record {index} has more fields than its header. Check quoting around commas.")
            comment = record_from_object(row, chosen)
            if comment:
                rows.append(comment)
            else:
                skipped.append(index)
            if len(rows) > MAX_COMMENTS:
                raise ImportProblem(f"Import up to {MAX_COMMENTS} comments at a time. Split this file into smaller files.")
        warnings = [f"Skipped {len(skipped)} records with empty comment text (record numbers: {', '.join(map(str, skipped[:10]))}{'…' if len(skipped) > 10 else ''})."] if skipped else []
        return rows, {"columns": headers, "selected_column": chosen, "skipped_empty": len(skipped), "warnings": warnings}
    except csv.Error as error:
        raise ImportProblem(f"Could not read the CSV: {error}") from None


def parse_x_copy(content: str) -> tuple[list[dict], dict]:
    """Recognize handle + middle-dot + time headers. Ambiguous UI text is retained."""
    lines = copy_lines(content)
    headers = []
    index = 0
    while index < len(lines):
        combined = X_HEADER.fullmatch(lines[index])
        end = index + 1
        if not combined and re.fullmatch(r"@[A-Za-z0-9_]{1,15}", lines[index]):
            look = index + 1
            while look < len(lines) and not lines[look]:
                look += 1
            if look < len(lines) and lines[look] in {"·", "•"}:
                look += 1
                while look < len(lines) and not lines[look]:
                    look += 1
                if look < len(lines):
                    combined = X_HEADER.fullmatch(f"{lines[index]} · {lines[look]}")
                    end = look + 1
            elif look < len(lines):
                combined = X_HEADER.fullmatch(f"{lines[index]} {lines[look]}")
                end = look + 1
        if combined:
            headers.append((index, end, combined[1], combined[2]))
            index = end
        else:
            index += 1
    if not headers:
        raise ImportProblem("No X comment headers were recognized. Use CSV/JSON, or choose plain text with one comment per line. Copied X headers should contain @handle, ·, and a timestamp.")
    rows, removed = [], 0
    # Preserve text before a header: it may be a first comment without its handle.
    prefix = "\n".join(lines[:headers[0][0]]).strip()
    if prefix:
        rows.append({"text": prefix})
    for number, (start, end, author, timestamp) in enumerate(headers):
        stop = headers[number + 1][0] if number + 1 < len(headers) else len(lines)
        body = "\n".join(lines[end:stop]).strip()
        removed += sum(bool(line) for line in lines[start:end])
        if body:
            rows.append({"text": body, "author": author, "posted_at": timestamp})
    return rows, {"removed_lines": removed, "warnings": [
        "X clipboard layouts vary. Handle and timestamp headers were separated; review and edit display names, engagement counts, and “Replying to” lines still inside the text. CSV/JSON exports provide more reliable boundaries.",
        "Only supplied text is included. Unexpanded replies and image/video content are not imported."]}


def parse_json(content: str) -> tuple[list[dict], dict]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, RecursionError):
        raise ImportProblem("The file is not valid JSON. Use a JSON array or a YouTube / X comment export.") from None
    records = data if isinstance(data, list) else data.get("items", data.get("comments", data.get("data"))) if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise ImportProblem("Expected a JSON array, or an object with an “items”, “comments”, or “data” array.")
    rows, skipped, incomplete = [], 0, 0
    includes = data.get("includes", {}) if isinstance(data, dict) else {}
    supplied_users = includes.get("users", []) if isinstance(includes, dict) else []
    users = {str(user.get("id")): user.get("username", "") for user in supplied_users if isinstance(user, dict)} if isinstance(supplied_users, list) else {}

    def add(record):
        nonlocal skipped
        if isinstance(record, str):
            comment = {"text": record.strip()} if record.strip() else None
        elif isinstance(record, dict):
            if isinstance(record.get("tweet"), dict):
                record = record["tweet"]
            note = record.get("note_post") or record.get("note_tweet")
            if isinstance(note, dict) and isinstance(note.get("text"), str):
                record = {**record, "full_text": note["text"]}
            metrics = record.get("public_metrics")
            if isinstance(metrics, dict):
                record = {**record, **metrics}
            username = users.get(str(record.get("author_id")))
            if isinstance(username, str) and username:
                record = {**record, "username": "@" + username}
            snippet = record.get("snippet")
            comment = record_from_object({**record, **snippet}) if isinstance(snippet, dict) else record_from_object(record)
        else:
            comment = None
        if comment:
            rows.append(comment)
        else:
            skipped += 1
        if len(rows) > MAX_COMMENTS:
            raise ImportProblem(f"Import up to {MAX_COMMENTS} comments at a time. Split this file into smaller files.")

    for record in records:
        snippet = record.get("snippet") if isinstance(record, dict) else None
        if isinstance(snippet, dict) and isinstance(snippet.get("topLevelComment"), dict):
            top = snippet["topLevelComment"]
            total_replies = snippet.get("totalReplyCount", "")
            add({**top, "totalReplyCount": total_replies})
            replies = record.get("replies", {})
            available = replies.get("comments", []) if isinstance(replies, dict) else []
            if not isinstance(available, list):
                available = []
            for reply in available:
                add(reply)
            if isinstance(total_replies, int) and total_replies > len(available):
                incomplete += 1
        else:
            add(record)
    warnings = []
    if skipped:
        warnings.append(f"Skipped {skipped} JSON records without a supported, nonempty comment-text field.")
    if incomplete:
        warnings.append(f"{incomplete} threads have replies not included in this export. Only supplied reply text can be imported.")
    return rows, {"skipped_empty": skipped, "warnings": warnings}


def preview(content: str, format: str = "auto", filename: str = "", column: str | None = None, source: str = "YouTube") -> dict:
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ImportProblem("The import exceeds 2 MB. Use a smaller file or paste fewer comments.")
    content = content.lstrip("\ufeff").strip()
    if not content or "\x00" in content:
        raise ImportProblem("Use nonempty UTF-8 text, CSV, or JSON. Binary files are not supported.")
    if format == "auto":
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        lines = [line for line in copy_lines(content) if line]
        has_header = any(HANDLE.fullmatch(lines[index]) and TIME.fullmatch(lines[index + 1]) for index in range(len(lines) - 1))
        if suffix in {"csv", "json"}:
            format = suffix
        elif content.startswith(("[", "{")):
            # A natural-language comment can start with these characters.
            try:
                json.loads(content)
                format = "json"
            except (json.JSONDecodeError, RecursionError):
                format = "youtube" if has_header else "lines"
        else:
            looks_like_csv = False
            if not has_header:
                for delimiter in (",", "\t", ";"):
                    try:
                        header = next(csv.reader(io.StringIO(content), delimiter=delimiter))
                        looks_like_csv = len(header) > 1 and any(field_key(key) in TEXT_FIELDS for key in header)
                    except (csv.Error, StopIteration):
                        pass
                    if looks_like_csv:
                        break
            has_x_header = any(X_HEADER.fullmatch(line) for line in lines) or bool(re.search(rf"@[A-Za-z0-9_]{{1,15}}\s*[·•]\s*{X_TIME}", content, re.I))
            format = "youtube" if has_header else "csv" if looks_like_csv else "x" if has_x_header else "lines"
    info = {}
    if format == "youtube":
        rows, info = parse_youtube_copy(content)
    elif format == "x":
        rows, info = parse_x_copy(content)
    elif format == "csv":
        rows, info = parse_csv(content, column)
    elif format == "json":
        rows, info = parse_json(content)
    elif format == "lines":
        rows = [{"text": line.strip()} for line in content.splitlines() if line.strip()]
        info["warnings"] = ["Plain text mode treats each nonempty line as one comment. Choose the copied-section format for page metadata or multiline comments."]
    else:
        raise ImportProblem("Choose auto-detect, copied YouTube, copied X, plain lines, CSV, or JSON.")
    if len(rows) > MAX_COMMENTS:
        raise ImportProblem(f"Found {len(rows)} comments. Import up to {MAX_COMMENTS} at a time; no rows were silently truncated.")
    if not rows and not info.get("needs_column"):
        raise ImportProblem("No comment text was found. Check the selected format or CSV column.")
    seen, duplicates, too_long = {}, 0, 0
    for index, row in enumerate(rows, start=1):
        row["id"] = f"row-{index}"
        row["characters"] = len(row["text"])
        row["valid"] = row["characters"] <= MAX_COMMENT_LENGTH
        too_long += not row["valid"]
        key = " ".join(unicodedata.normalize("NFKC", row["text"]).lower().split())
        row["duplicate_of"] = seen.get(key)
        duplicates += key in seen
        seen.setdefault(key, row["id"])
    return {"format": format, "source": source, "comments": rows, "total": len(rows), "duplicates": duplicates,
            "too_long": too_long, "removed_lines": 0, "warnings": [], "needs_column": False, **info}
