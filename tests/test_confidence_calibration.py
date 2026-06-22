
import pytest

from services.confidence_calibration import (
    calibrate_prediction,
    confidence_bucket_summary,
    confidence_level,
    expected_calibration_error,
    softmax,
    temperature_scaled_softmax,
)


def test_softmax_outputs_valid_probabilities():
    probs = softmax([2.0, 1.0, 0.5])

    assert len(probs) == 3
    assert pytest.approx(float(probs.sum()), rel=1e-6) == 1.0
    assert probs[0] > probs[1] > probs[2]


def test_temperature_scaling_softens_confidence():
    raw = softmax([5.0, 1.0, 0.5])
    calibrated = temperature_scaled_softmax([5.0, 1.0, 0.5], temperature=2.0)

    assert calibrated[0] < raw[0]
    assert pytest.approx(float(calibrated.sum()), rel=1e-6) == 1.0


def test_temperature_must_be_positive():
    with pytest.raises(ValueError):
        temperature_scaled_softmax([1.0, 2.0], temperature=0)


def test_confidence_level_buckets():
    assert confidence_level(0.90) == "high_confidence"
    assert confidence_level(0.65) == "medium_confidence"
    assert confidence_level(0.30) == "low_confidence"


def test_confidence_level_rejects_invalid_values():
    with pytest.raises(ValueError):
        confidence_level(1.5)


def test_calibrate_prediction_returns_safe_response():
    result = calibrate_prediction(
        class_names=["Healthy", "Leaf Blight", "Aphids"],
        logits=[0.2, 3.0, 0.5],
        temperature=1.5,
    )

    output = result.to_dict()

    assert output["prediction"] == "Leaf Blight"
    assert "raw_confidence" in output
    assert "calibrated_confidence" in output
    assert output["confidence_level"] in {
        "high_confidence",
        "medium_confidence",
        "low_confidence",
    }


def test_low_confidence_prediction_includes_warning():
    result = calibrate_prediction(
        class_names=["Healthy", "Leaf Blight", "Aphids"],
        logits=[1.0, 1.0, 1.0],
        temperature=1.5,
    )

    output = result.to_dict()

    assert output["confidence_level"] == "low_confidence"
    assert output["warning"] is not None


def test_expected_calibration_error_valid_result():
    ece = expected_calibration_error(
        confidences=[0.9, 0.8, 0.4, 0.3],
        predictions_correct=[True, True, False, True],
        n_bins=4,
    )

    assert 0.0 <= ece <= 1.0


def test_expected_calibration_error_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        expected_calibration_error(
            confidences=[0.9, 0.8],
            predictions_correct=[True],
        )


def test_confidence_bucket_summary_counts_levels():
    summary = confidence_bucket_summary([0.95, 0.75, 0.45, 0.20])

    assert summary["high_confidence"] == 1
    assert summary["medium_confidence"] == 1
    assert summary["low_confidence"] == 2
