"""Sparse, classical NLP. Explanations exactly decompose a pairwise logit margin."""

from pathlib import Path
import re

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion

from hatelens.text import LABELS, TOKEN_PATTERN, highlight_spans, normalize


def make_vectorizer(min_df: int = 2) -> FeatureUnion:
    return FeatureUnion([
        ("word", TfidfVectorizer(preprocessor=normalize, token_pattern=TOKEN_PATTERN,
                                ngram_range=(1, 2), min_df=min_df, max_features=45000, sublinear_tf=True)),
        ("char", TfidfVectorizer(preprocessor=normalize, analyzer="char_wb",
                                ngram_range=(3, 5), min_df=min_df, max_features=30000, sublinear_tf=True)),
    ], transformer_weights={"word": 1.0, "char": 0.6})


def make_classifier() -> LogisticRegression:
    return LogisticRegression(C=3.0, solver="saga", max_iter=500, tol=1e-3,
                              class_weight="balanced", random_state=42)


class HateLensModel:
    def __init__(self, vectorizer, classifier, metadata: dict, audit: dict | None = None):
        self.vectorizer = vectorizer
        self.classifier = classifier
        self.metadata = metadata
        self.audit = audit or {}
        self.feature_names = vectorizer.get_feature_names_out()

    @classmethod
    def load(cls, path: Path):
        # This is a locally trained artifact, never an uploaded/untrusted pickle.
        artifact = joblib.load(path)
        return cls(**artifact)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        joblib.dump({"vectorizer": self.vectorizer, "classifier": self.classifier,
                     "metadata": self.metadata, "audit": self.audit}, temporary, compress=3)
        temporary.replace(path)

    def predict(self, text: str) -> dict:
        matrix = self.vectorizer.transform([text]).tocsr()
        probabilities = self.classifier.predict_proba(matrix)[0]
        order = np.argsort(probabilities)[::-1]
        winner, runner = int(order[0]), int(order[1])
        label = str(self.classifier.classes_[winner])
        comparison = str(self.classifier.classes_[runner])
        delta = self.classifier.coef_[winner] - self.classifier.coef_[runner]
        contributions = matrix.data * delta[matrix.indices]
        features = []
        for position in np.argsort(np.abs(contributions))[::-1][:10]:
            name = self.feature_names[matrix.indices[position]]
            kind, feature = name.split("__", 1)
            features.append({"feature": feature, "kind": kind, "contribution": float(contributions[position])})
        base_margin = float(self.classifier.intercept_[winner] - self.classifier.intercept_[runner])
        all_contributions = float(contributions.sum())
        word_vectorizer = self.vectorizer.transformer_list[0][1]
        tokens = word_vectorizer.build_tokenizer()(normalize(text))
        coverage = sum(token in word_vectorizer.vocabulary_ for token in tokens) / max(len(tokens), 1)
        score = float(probabilities[winner])
        reasons = []
        if matrix.nnz == 0 or coverage < 0.35:
            reasons.append("Little familiar vocabulary; the model may be outside its training domain.")
        if score < 0.60:
            reasons.append("No category has a model score of 60% or more.")
        if float(probabilities[winner] - probabilities[runner]) < 0.15:
            reasons.append("The two leading categories are less than 15 percentage points apart.")
        if len(tokens) < 3:
            reasons.append("This short comment may need surrounding context.")
        if re.search(r"[^\x00-\x7f]", text) and sum(bool(re.search(r"[a-z]", token)) for token in tokens) < len(tokens) / 2:
            reasons.append("This model was evaluated on English text only.")
        return {
            "text": text, "label": label, "score": score,
            "probabilities": {str(name): float(probability) for name, probability in zip(self.classifier.classes_, probabilities)},
            "needs_review": bool(reasons), "review_reasons": reasons,
            "vocabulary_coverage": coverage, "model_version": self.metadata["version"],
            "explanation": {
                "comparison_label": comparison, "features": features,
                "highlights": highlight_spans(text, features),
                "base_margin": base_margin, "feature_margin": all_contributions,
                "other_features_margin": all_contributions - sum(feature["contribution"] for feature in features),
                "decision_margin": base_margin + all_contributions,
                "method": "TF-IDF × (predicted-class weight − runner-up weight). Values are logit contributions, not probabilities or causal explanations.",
            },
        }

    def labels_for(self, texts: list[str]) -> list[str]:
        return self.classifier.predict(self.vectorizer.transform(texts)).tolist()
