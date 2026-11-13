from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from hatelens.app import create_app
from hatelens.config import Settings
from hatelens.evaluation import group_audit, metrics, probe_audit
from hatelens.model import HateLensModel, make_classifier, make_vectorizer


@pytest.fixture(scope="session")
def model():
    # Tiny synthetic fixtures exercise mechanics, never serve as product training/evaluation.
    examples = {
        "hate": ["all groupalpha people must leave", "groupalpha are vermin", "groupbeta should be excluded", "no groupbeta people are welcome"],
        "offensive": ["your argument is stupid", "you are an idiot", "what a horrible stupid comment", "this is a damn awful idea"],
        "neither": ["everyone is welcome here", "thank you for the lovely comment", "I do not hate groupalpha", "I support equal rights for everyone"],
    }
    texts, labels = [], []
    for label, comments in examples.items():
        texts.extend(comments)
        labels.extend([label] * len(comments))
    vectorizer = make_vectorizer(min_df=1)
    matrix = vectorizer.fit_transform(texts)
    classifier = make_classifier().fit(matrix, labels)
    report = metrics(labels, classifier.predict(matrix).tolist())
    metadata = {"version": "test-model", "test": report, "validation": report, "comparison": [],
                "language": "English", "algorithm": "Logistic Regression", "features": "Word + character TF-IDF",
                "training_samples": len(texts), "feature_count": matrix.shape[1], "trained_at": "2026-01-01T00:00:00+00:00",
                "sklearn_version": "test", "probabilities_calibrated": False}
    result = HateLensModel(vectorizer, classifier, metadata)
    result.audit = {"groups": [], "probes": probe_audit(result), "test_samples": len(texts)}
    return result


@pytest.fixture
def client(tmp_path, model):
    artifact = tmp_path / "model.joblib"
    model.save(artifact)
    app = create_app(Settings(model_path=artifact, database_path=tmp_path / "records.sqlite3"))
    with TestClient(app) as client:
        yield client
