"""Download pinned public data and preserve the authors' evaluation splits."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import urllib.request

from hatelens.text import normalize

REVISION = "01d742279dac941981f53806154481c0e15ee686"
SOURCE = "https://github.com/hate-alert/HateXplain"
LABEL_MAP = {"hatespeech": "hate", "offensive": "offensive", "normal": "neither"}


def download(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {"source": SOURCE, "revision": REVISION, "files": {}}
    for name in ("dataset.json", "post_id_divisions.json"):
        url = f"https://raw.githubusercontent.com/hate-alert/HateXplain/{REVISION}/Data/{name}"
        with urllib.request.urlopen(url, timeout=90) as response:
            content = response.read()
        json.loads(content)  # Never replace a valid local file with a network error page.
        temporary = directory / (name + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(directory / name)
        manifest["files"][name] = {"url": url, "sha256": hashlib.sha256(content).hexdigest()}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def load_splits(directory: Path) -> tuple[dict, dict]:
    data = json.loads((directory / "dataset.json").read_text())
    divisions = json.loads((directory / "post_id_divisions.json").read_text())
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, info in manifest["files"].items():
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if digest != info["sha256"]:
            raise ValueError(f"Dataset integrity check failed for {name}; download it again.")
    splits = {}
    seen = set()
    skipped = {"no_majority": 0, "empty": 0, "duplicate_text": 0}
    # Evaluation has precedence, so no normalized test text enters validation/training.
    for split in ("test", "val", "train"):
        rows = []
        for post_id in divisions[split]:
            post = data[post_id]
            votes = Counter(annotation["label"] for annotation in post["annotators"])
            label, count = votes.most_common(1)[0]
            if count < 2 or label not in LABEL_MAP:
                skipped["no_majority"] += 1
                continue
            text = " ".join(post["post_tokens"])
            key = normalize(text)
            if not key:
                skipped["empty"] += 1
                continue
            if key in seen:
                skipped["duplicate_text"] += 1
                continue
            seen.add(key)
            targets = Counter(target for annotation in post["annotators"] for target in set(annotation["target"]))
            groups = sorted(target for target, count in targets.items() if count >= 2 and target.lower() not in {"none", "other"})
            rows.append({"id": post_id, "text": text, "label": LABEL_MAP[label], "groups": groups})
        splits[split] = rows
    manifest["skipped"] = skipped
    manifest["split_sizes"] = {key: len(value) for key, value in splits.items()}
    return splits, manifest


def merge_feedback(splits: dict, feedback: list[dict]) -> tuple[list[dict], dict]:
    """Only adjudicated labels enter training; held-out text is always excluded."""
    held_out = {normalize(row["text"]) for key in ("val", "test") for row in splits[key]}
    training = {normalize(row["text"]): dict(row) for row in splits["train"]}
    counts = {"applied": 0, "held_out_excluded": 0, "unreviewed_excluded": 0}
    for row in feedback:
        if row.get("status") != "accepted" or row.get("reviewed_label") not in LABEL_MAP.values():
            counts["unreviewed_excluded"] += 1
            continue
        key = normalize(row["text"])
        if key in held_out:
            counts["held_out_excluded"] += 1
            continue
        if not key:
            continue
        training[key] = {"id": f"feedback-{row['id']}", "text": row["text"], "label": row["reviewed_label"], "groups": []}
        counts["applied"] += 1
    return list(training.values()), counts
