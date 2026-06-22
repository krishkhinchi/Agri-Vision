
"""
Confidence calibration utilities for Agri-Vision predictions.

This module provides lightweight post-processing for model confidence scores:
- softmax with temperature scaling
- Expected Calibration Error (ECE)
- confidence level bucketing
- uncertainty-aware prediction responses

The implementation is dependency-light and works with NumPy arrays, so it can be
tested without loading heavy deep learning model weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import numpy as np


@dataclass(frozen=True)
class CalibrationResult:
    """Structured result for a calibrated prediction."""

    prediction: str
    raw_confidence: float
    calibrated_confidence: float
    confidence_level: str
    warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return result as a JSON-serializable dictionary."""
        return {
            "prediction": self.prediction,
            "raw_confidence": round(float(self.raw_confidence), 4),
            "calibrated_confidence": round(float(self.calibrated_confidence), 4),
            "confidence_level": self.confidence_level,
            "warning": self.warning,
        }


def softmax(logits: Iterable[float]) -> np.ndarray:
    """Compute numerically stable softmax probabilities."""
    values = np.asarray(logits, dtype=float)

    if values.ndim != 1:
        raise ValueError("logits must be a one-dimensional array")

    if values.size == 0:
        raise ValueError("logits cannot be empty")

    shifted = values - np.max(values)
    exp_values = np.exp(shifted)
    return exp_values / np.sum(exp_values)


def temperature_scaled_softmax(
    logits: Iterable[float],
    temperature: float = 1.0,
) -> np.ndarray:
    """
    Apply temperature scaling before softmax.

    temperature > 1.0 softens overconfident predictions.
    temperature < 1.0 sharpens predictions.
    """
    if temperature <= 0:
        raise ValueError("temperature must be greater than 0")

    values = np.asarray(logits, dtype=float)
    return softmax(values / temperature)


def confidence_level(
    confidence: float,
    high_threshold: float = 0.80,
    medium_threshold: float = 0.50,
) -> str:
    """Convert numeric confidence into a user-friendly confidence bucket."""
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")

    if confidence >= high_threshold:
        return "high_confidence"

    if confidence >= medium_threshold:
        return "medium_confidence"

    return "low_confidence"


def uncertainty_warning(level: str) -> Optional[str]:
    """Return a safe warning message for uncertain predictions."""
    if level == "low_confidence":
        return (
            "Prediction confidence is low. Please capture a clearer image "
            "or consult an agricultural expert before taking action."
        )

    if level == "medium_confidence":
        return (
            "Prediction confidence is moderate. Consider verifying with another image."
        )

    return None


def calibrate_prediction(
    class_names: Iterable[str],
    logits: Iterable[float],
    temperature: float = 1.5,
) -> CalibrationResult:
    """
    Return prediction with raw and calibrated confidence.

    Parameters
    ----------
    class_names:
        Ordered class labels matching the logits.
    logits:
        Raw model logits or score-like values.
    temperature:
        Temperature value used for calibration.
    """
    labels = list(class_names)
    values = np.asarray(logits, dtype=float)

    if len(labels) != len(values):
        raise ValueError("class_names and logits must have the same length")

    raw_probs = softmax(values)
    calibrated_probs = temperature_scaled_softmax(values, temperature)

    pred_index = int(np.argmax(calibrated_probs))
    calibrated_conf = float(calibrated_probs[pred_index])
    raw_conf = float(raw_probs[pred_index])
    level = confidence_level(calibrated_conf)

    return CalibrationResult(
        prediction=labels[pred_index],
        raw_confidence=raw_conf,
        calibrated_confidence=calibrated_conf,
        confidence_level=level,
        warning=uncertainty_warning(level),
    )


def expected_calibration_error(
    confidences: Iterable[float],
    predictions_correct: Iterable[bool],
    n_bins: int = 10,
) -> float:
    """
    Compute Expected Calibration Error.

    ECE compares average confidence with actual accuracy inside confidence bins.
    Lower values indicate better calibration.
    """
    conf = np.asarray(confidences, dtype=float)
    correct = np.asarray(predictions_correct, dtype=bool)

    if conf.ndim != 1 or correct.ndim != 1:
        raise ValueError("confidences and predictions_correct must be one-dimensional")

    if len(conf) != len(correct):
        raise ValueError("confidences and predictions_correct must have the same length")

    if len(conf) == 0:
        raise ValueError("inputs cannot be empty")

    if np.any((conf < 0) | (conf > 1)):
        raise ValueError("all confidence values must be between 0 and 1")

    if n_bins <= 0:
        raise ValueError("n_bins must be greater than 0")

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0

    for bin_idx in range(n_bins):
        lower = bin_edges[bin_idx]
        upper = bin_edges[bin_idx + 1]

        if bin_idx == 0:
            mask = (conf >= lower) & (conf <= upper)
        else:
            mask = (conf > lower) & (conf <= upper)

        if not np.any(mask):
            continue

        bin_confidence = float(np.mean(conf[mask]))
        bin_accuracy = float(np.mean(correct[mask]))
        bin_weight = float(np.mean(mask))

        ece += bin_weight * abs(bin_accuracy - bin_confidence)

    return float(ece)


def confidence_bucket_summary(
    confidences: Iterable[float],
) -> Dict[str, int]:
    """Count predictions in high, medium, and low confidence buckets."""
    summary = {
        "high_confidence": 0,
        "medium_confidence": 0,
        "low_confidence": 0,
    }

    for value in confidences:
        summary[confidence_level(float(value))] += 1

    return summary
