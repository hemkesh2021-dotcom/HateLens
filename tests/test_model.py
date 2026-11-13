import numpy as np
import pytest

from hatelens.model import HateLensModel
from hatelens.text import normalize


def test_negation_and_apostrophes_survive_preprocessing():
    assert normalize("I DO NOT hate them. I’m @someone. https://example.com") == "i do not hate them. i'm usertoken . urltoken"


@pytest.mark.parametrize("text", ["I do not hate groupalpha", "what a stupid comment", "everyone is welcome here", "👋 Everyone is welcome here"])
def test_feature_attributions_exactly_reconstruct_logit_margin(model, text):
    result = model.predict(text)
    explanation = result["explanation"]
    matrix = model.vectorizer.transform([text])
    logits = model.classifier.decision_function(matrix)[0]
    classes = list(model.classifier.classes_)
    expected = logits[classes.index(result["label"])] - logits[classes.index(explanation["comparison_label"])]
    reconstructed = sum(feature["contribution"] for feature in explanation["features"]) + explanation["other_features_margin"] + explanation["base_margin"]
    assert reconstructed == pytest.approx(expected, abs=1e-9)
    assert explanation["decision_margin"] == pytest.approx(expected, abs=1e-9)
    assert sum(result["probabilities"].values()) == pytest.approx(1)
    assert result["score"] == max(result["probabilities"].values())
    for span in explanation["highlights"]:
        assert text[span["start"]:span["end"]].lower() == span["feature"]


def test_unseen_language_is_sent_for_review(model):
    result = model.predict("你好 世界 欢迎 大家")
    assert result["needs_review"] is True
    assert result["vocabulary_coverage"] == 0
    assert result["explanation"]["features"] == []


def test_local_artifact_round_trip_preserves_predictions(tmp_path, model):
    path = tmp_path / "model.joblib"
    model.save(path)
    loaded = HateLensModel.load(path)
    assert loaded.predict("everyone is welcome here") == model.predict("everyone is welcome here")
