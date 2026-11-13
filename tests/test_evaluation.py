import pytest

from hatelens.evaluation import error_rate, group_audit
from hatelens.dataset import merge_feedback


def test_group_error_rates_use_correct_denominators():
    rows = [
        {"label": "hate", "groups": ["A", "B"]},
        {"label": "neither", "groups": ["A"]},
        {"label": "offensive", "groups": ["A"]},
        {"label": "hate", "groups": ["B"]},
    ]
    audit = {row["group"]: row for row in group_audit(rows, ["neither", "hate", "offensive", "hate"])}
    assert audit["A"]["false_positive"]["rate"] == 0.5
    assert audit["A"]["false_negative"]["rate"] == 1
    assert audit["B"]["false_positive"]["rate"] is None
    assert audit["B"]["false_negative"]["rate"] == 0.5
    assert all(row["small_sample"] for row in audit.values())


def test_wilson_interval_does_not_imply_certainty_from_zero_observed_errors():
    rate = error_rate(0, 10)
    assert rate["rate"] == 0
    assert rate["interval"][0] == pytest.approx(0)
    assert 0.2 < rate["interval"][1] < 0.4
    assert error_rate(0, 0)["interval"] is None


def test_only_reviewed_feedback_enters_training_without_held_out_leakage():
    splits = {"train": [{"id": "train", "text": "training example", "label": "neither", "groups": []}],
              "val": [{"text": "validation example"}], "test": [{"text": "test example"}]}
    feedback = [
        {"id": "a", "text": "new training example", "status": "accepted", "reviewed_label": "offensive"},
        {"id": "b", "text": " Test   EXAMPLE ", "status": "accepted", "reviewed_label": "hate"},
        {"id": "c", "text": "validation example", "status": "accepted", "reviewed_label": "hate"},
        {"id": "d", "text": "pending example", "status": "pending", "reviewed_label": None},
        {"id": "e", "text": "training example", "status": "accepted", "reviewed_label": "offensive"},
        {"id": "f", "text": "rejected example", "status": "rejected", "reviewed_label": "hate"},
    ]
    rows, counts = merge_feedback(splits, feedback)
    assert len(rows) == 2
    assert {row["label"] for row in rows} == {"offensive"}
    assert counts == {"applied": 2, "held_out_excluded": 2, "unreviewed_excluded": 2}
