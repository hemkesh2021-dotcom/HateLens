"""Reproducible offline training. Human feedback produces a candidate, never auto-deploys."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import warnings

import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import LinearSVC

from hatelens.config import ROOT
from hatelens.dataset import download, load_splits, merge_feedback
from hatelens.evaluation import group_audit, metrics, probe_audit
from hatelens.model import HateLensModel, make_classifier, make_vectorizer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download the pinned HateXplain dataset.")
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "model.joblib")
    parser.add_argument("--compare", action="store_true", help="Evaluate Naive Bayes and Linear SVM on validation data.")
    parser.add_argument("--with-feedback", type=Path, help="Read accepted feedback from a local HateLens SQLite database.")
    arguments = parser.parse_args()
    if arguments.download:
        print("Downloading pinned HateXplain data…", flush=True)
        download(arguments.data)
    splits, dataset = load_splits(arguments.data)
    rows = splits["train"]
    feedback_summary = {"applied": 0, "held_out_excluded": 0, "unreviewed_excluded": 0}
    feedback_ids = []
    if arguments.with_feedback:
        if arguments.output.resolve() == (ROOT / "artifacts" / "model.joblib").resolve():
            parser.error("Feedback retraining needs a separate --output, for example artifacts/candidate.joblib.")
        connection = sqlite3.connect(f"file:{arguments.with_feedback.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        with connection:
            feedback = [dict(row) for row in connection.execute(
                "SELECT f.*, p.text FROM feedback f JOIN predictions p ON p.id=f.prediction_id ORDER BY f.reviewed_at, f.id")]
        connection.close()
        rows, feedback_summary = merge_feedback(splits, feedback)
        feedback_ids = [row["id"] for row in feedback if row["status"] == "accepted"]
    print(f"Training on {len(rows):,} posts; validation {len(splits['val']):,}; test {len(splits['test']):,}.", flush=True)
    vectorizer = make_vectorizer()
    training_matrix = vectorizer.fit_transform([row["text"] for row in rows])
    validation_matrix = vectorizer.transform([row["text"] for row in splits["val"]])
    truth = [row["label"] for row in rows]
    classifier = make_classifier()
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always", ConvergenceWarning)
        classifier.fit(training_matrix, truth)
    converged = not any(issubclass(warning.category, ConvergenceWarning) for warning in recorded)
    if not converged:
        raise RuntimeError("The classifier did not converge. No artifact was saved; increase max_iter before retrying.")
    now = datetime.now(timezone.utc)
    training_hash = hashlib.sha256(json.dumps([(row["text"], row["label"]) for row in rows], ensure_ascii=False).encode()).hexdigest()
    metadata = {
        "version": f"hl-{now.strftime('%Y%m%d-%H%M%S')}-{training_hash[:6]}",
        "trained_at": now.isoformat(), "algorithm": "Logistic Regression", "features": "Word + character TF-IDF",
        "language": "English", "feature_count": int(training_matrix.shape[1]), "training_samples": len(rows),
        "sklearn_version": sklearn.__version__, "random_seed": 42, "converged": converged,
        "dataset": dataset, "training_sha256": training_hash, "feedback": feedback_summary,
        "reviewed_feedback_ids": feedback_ids, "probabilities_calibrated": False,
        "thresholds": {"review_below_score": 0.60, "review_below_margin": 0.15, "review_below_word_coverage": 0.35},
    }
    model = HateLensModel(vectorizer, classifier, metadata)
    validation_truth = [row["label"] for row in splits["val"]]
    metadata["validation"] = metrics(validation_truth, classifier.predict(validation_matrix).tolist())
    metadata["comparison"] = [{"model": "Logistic Regression", "macro_f1": metadata["validation"]["macro_f1"]}]
    if arguments.compare:
        for name, baseline in [("Multinomial Naive Bayes", MultinomialNB(alpha=0.5)),
                               ("Linear SVM", LinearSVC(C=1.0, class_weight="balanced", random_state=42, max_iter=5000))]:
            print(f"Comparing {name} on the validation split…", flush=True)
            baseline.fit(training_matrix, truth)
            result = metrics(validation_truth, baseline.predict(validation_matrix).tolist())
            metadata["comparison"].append({"model": name, "macro_f1": result["macro_f1"]})
    test_predictions = model.labels_for([row["text"] for row in splits["test"]])
    metadata["test"] = metrics([row["label"] for row in splits["test"]], test_predictions)
    model.audit = {"groups": group_audit(splits["test"], test_predictions), "probes": probe_audit(model),
                   "dataset": "HateXplain held-out test split", "test_samples": len(splits["test"]),
                   "group_definition": "Target communities selected by at least two dataset annotators. These are not inferred author identities. Groups can overlap.",
                   "rate_definition": "Hate speech versus all other labels. FPR = false hate flags / non-hateful examples; FNR = missed hate / hateful examples.",
                   "interval_definition": "95% Wilson intervals. Fewer than 20 positives or negatives is marked as a small sample."}
    model.save(arguments.output)
    report_path = arguments.output.with_suffix(".report.json")
    report_path.write_text(json.dumps({"model": metadata, "audit": model.audit}, indent=2))
    print(json.dumps({"artifact": str(arguments.output), "report": str(report_path),
                      "test_macro_f1": metadata["test"]["macro_f1"], "validation_baselines": metadata["comparison"],
                      "probe_passes": f"{model.audit['probes']['passed']}/{model.audit['probes']['total']}"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
