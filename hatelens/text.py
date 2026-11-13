"""One shared preprocessing function for training, inference, and deduplication."""

import re
import unicodedata

LABELS = ("hate", "offensive", "neither")
LABEL_NAMES = {"hate": "Hate speech", "offensive": "Offensive language", "neither": "Neither"}
TOKEN_PATTERN = r"(?u)\b\w+(?:'\w+)*\b"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    text = re.sub(r"https?://\S+|www\.\S+|<url>", " urltoken ", text)
    text = re.sub(r"(?<!\w)@[\w]+|<user>", " usertoken ", text)
    return re.sub(r"\s+", " ", text).strip()


def highlight_spans(text: str, features: list[dict]) -> list[dict]:
    """Only mark visible word features; character fragments stay in the breakdown."""
    candidates = []
    for feature in features:
        if feature["kind"] != "word" or feature["contribution"] <= 0:
            continue
        pattern = r"(?<!\w)" + r"\s+".join(re.escape(part) for part in feature["feature"].split()) + r"(?!\w)"
        pattern = pattern.replace("'", "['’]")
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            candidates.append({"start": match.start(), "end": match.end(), "feature": feature["feature"]})
    selected = []
    for candidate in sorted(candidates, key=lambda span: (-(span["end"] - span["start"]), span["start"])):
        if not any(candidate["start"] < span["end"] and candidate["end"] > span["start"] for span in selected):
            selected.append(candidate)
    return sorted(selected, key=lambda span: span["start"])
