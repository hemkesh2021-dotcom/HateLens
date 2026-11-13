"""Measured classification errors and transparent, limited diagnostic probes."""

import math

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from hatelens.text import LABELS


def metrics(truth: list[str], predictions: list[str]) -> dict:
    return {
        "samples": len(truth),
        "accuracy": float(accuracy_score(truth, predictions)),
        "macro_f1": float(f1_score(truth, predictions, labels=list(LABELS), average="macro", zero_division=0)),
        "per_class": classification_report(truth, predictions, labels=list(LABELS), output_dict=True, zero_division=0),
        "confusion_matrix": confusion_matrix(truth, predictions, labels=list(LABELS)).tolist(),
        "label_order": list(LABELS),
    }


def error_rate(errors: int, denominator: int) -> dict:
    if denominator == 0:
        return {"errors": errors, "total": 0, "rate": None, "interval": None}
    probability = errors / denominator
    z = 1.96
    denominator_wilson = 1 + z * z / denominator
    center = (probability + z * z / (2 * denominator)) / denominator_wilson
    radius = z * math.sqrt(probability * (1 - probability) / denominator + z * z / (4 * denominator * denominator)) / denominator_wilson
    return {"errors": errors, "total": denominator, "rate": probability,
            "interval": [max(0, center - radius), min(1, center + radius)]}


def group_audit(rows: list[dict], predictions: list[str]) -> list[dict]:
    groups = sorted({group for row in rows for group in row["groups"]})
    result = []
    for group in groups:
        pairs = [(row["label"], predicted) for row, predicted in zip(rows, predictions) if group in row["groups"]]
        positives = sum(actual == "hate" for actual, _ in pairs)
        negatives = len(pairs) - positives
        false_positive = sum(actual != "hate" and predicted == "hate" for actual, predicted in pairs)
        false_negative = sum(actual == "hate" and predicted != "hate" for actual, predicted in pairs)
        result.append({"group": group, "samples": len(pairs),
                       "false_positive": error_rate(false_positive, negatives),
                       "false_negative": error_rate(false_negative, positives),
                       "small_sample": min(positives, negatives) < 20})
    return sorted(result, key=lambda row: -row["samples"])


PROBE_GROUPS = ["women", "men", "Muslims", "Christians", "Jewish people", "gay people", "Black people", "white people"]
PROBE_TEMPLATES = [
    ("Everyday mention", "I work with {group} every day.", "neither"),
    ("Support", "I support equal rights for {group}.", "neither"),
    ("Welcome", "Our neighborhood welcomes {group}.", "neither"),
    ("Negation", "We should not discriminate against {group}.", "neither"),
    ("Opposing hate", "It is wrong to say that all {group} should leave.", "neither"),
    ("Exclusion", "All {group} should be driven out of our community.", "hate"),
    ("Dehumanization", "All {group} are vermin.", "hate"),
]


def probe_audit(model) -> dict:
    templates = []
    for category, template, expected in PROBE_TEMPLATES:
        texts = [template.format(group=group) for group in PROBE_GROUPS]
        matrix = model.vectorizer.transform(texts)
        probabilities = model.classifier.predict_proba(matrix)
        predictions = model.classifier.predict(matrix)
        hate_index = list(model.classifier.classes_).index("hate")
        cases = [{"group": group, "text": text, "expected": expected, "predicted": str(predicted),
                  "hate_score": float(probability[hate_index]), "passed": bool(predicted == expected)}
                 for group, text, predicted, probability in zip(PROBE_GROUPS, texts, predictions, probabilities)]
        scores = [case["hate_score"] for case in cases]
        templates.append({"category": category, "template": template, "cases": cases,
                          "score_spread": max(scores) - min(scores), "passed": sum(case["passed"] for case in cases)})
    return {"templates": templates, "total": sum(len(row["cases"]) for row in templates),
            "passed": sum(row["passed"] for row in templates),
            "description": "56 small, handcrafted identity-swap probes. Diagnostic examples, not a representative fairness benchmark or the HateCheck dataset."}
