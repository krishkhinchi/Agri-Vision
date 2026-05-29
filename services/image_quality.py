"""
Lightweight pre-inference image quality validation.

The checks here are intentionally heuristic and fast. They are designed to warn
users when image quality may reduce model reliability without blocking normal
prediction flow unless the image is visually unusable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageQualityConfig:
    min_width: int = 224
    min_height: int = 224
    blur_warning_threshold: float = 80.0
    blur_poor_threshold: float = 35.0
    dark_mean_threshold: float = 45.0
    bright_mean_threshold: float = 215.0
    overexposed_pixel_ratio: float = 0.55
    blank_variance_threshold: float = 12.0
    blank_entropy_threshold: float = 2.0
    max_aspect_ratio: float = 3.0
    hard_min_dimension: int = 32


DEFAULT_CONFIG = ImageQualityConfig()


def _base_result() -> Dict[str, Any]:
    return {
        "passed": True,
        "quality_score": 100,
        "status": "Excellent",
        "warnings": [],
        "suggestions": [],
        "metrics": {},
        "is_blocking": False,
    }


def _entropy(gray: np.ndarray) -> float:
    histogram = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    total = float(histogram.sum())
    if total <= 0:
        return 0.0
    probabilities = histogram / total
    probabilities = probabilities[probabilities > 0]
    return float(-(probabilities * np.log2(probabilities)).sum())


def _add_issue(
    result: Dict[str, Any],
    warning: str,
    suggestion: str,
    penalty: int,
    blocking: bool = False,
) -> None:
    if warning not in result["warnings"]:
        result["warnings"].append(warning)
    if suggestion not in result["suggestions"]:
        result["suggestions"].append(suggestion)
    result["quality_score"] = max(0, int(result["quality_score"]) - penalty)
    if blocking:
        result["is_blocking"] = True


def _status_from_score(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Poor"


def validate_image_quality(
    image: np.ndarray,
    config: ImageQualityConfig = DEFAULT_CONFIG,
) -> Dict[str, Any]:
    """
    Validate a decoded BGR or RGB image and return an API-safe result dict.

    Poor quality images are warning-based by default. Completely unusable
    images, such as extremely tiny or blank frames, are marked as blocking.
    """
    result = _base_result()

    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        _add_issue(
            result,
            "Image data is missing or corrupted.",
            "Upload a valid JPG or PNG crop image.",
            100,
            blocking=True,
        )
        result["passed"] = False
        result["status"] = "Invalid"
        return result

    if image.ndim == 2:
        gray = image
        height, width = image.shape[:2]
    elif image.ndim == 3 and image.shape[2] >= 3:
        height, width = image.shape[:2]
        gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    else:
        _add_issue(
            result,
            "Unsupported image structure.",
            "Upload a standard color crop photo.",
            100,
            blocking=True,
        )
        result["passed"] = False
        result["status"] = "Invalid"
        return result

    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    pixel_variance = float(np.var(gray))
    entropy = _entropy(gray)
    aspect_ratio = float(max(width, height) / max(1, min(width, height)))
    dark_ratio = float(np.mean(gray <= 30))
    bright_ratio = float(np.mean(gray >= 245))

    result["metrics"] = {
        "blur_score": round(blur_score, 2),
        "brightness": round(brightness, 2),
        "resolution": f"{width}x{height}",
        "width": int(width),
        "height": int(height),
        "aspect_ratio": round(aspect_ratio, 2),
        "pixel_variance": round(pixel_variance, 2),
        "entropy": round(entropy, 2),
        "dark_pixel_ratio": round(dark_ratio, 3),
        "bright_pixel_ratio": round(bright_ratio, 3),
    }

    if width < config.hard_min_dimension or height < config.hard_min_dimension:
        _add_issue(
            result,
            "Image resolution is too small to analyze reliably.",
            "Upload a larger crop image with the leaf clearly visible.",
            100,
            blocking=True,
        )
    elif width < config.min_width or height < config.min_height:
        _add_issue(
            result,
            "Image resolution is low.",
            "Move closer to the crop leaf or use a higher resolution photo.",
            20,
        )

    if blur_score < config.blur_poor_threshold:
        _add_issue(
            result,
            "Image appears very blurry or out of focus.",
            "Hold the camera steady and refocus on the affected leaf.",
            30,
        )
    elif blur_score < config.blur_warning_threshold:
        _add_issue(
            result,
            "Image may be slightly blurry.",
            "Retake the photo with a steady camera for better accuracy.",
            15,
        )

    if brightness < config.dark_mean_threshold or dark_ratio > 0.65:
        _add_issue(
            result,
            "Lighting is too dark.",
            "Capture the image in brighter natural light.",
            25,
        )
    elif brightness > config.bright_mean_threshold or bright_ratio > config.overexposed_pixel_ratio:
        _add_issue(
            result,
            "Image appears overexposed.",
            "Avoid harsh sunlight or glare on the leaf surface.",
            25,
        )

    if aspect_ratio > config.max_aspect_ratio:
        _add_issue(
            result,
            "Image aspect ratio looks distorted.",
            "Retake the photo without stretching or cropping it too narrowly.",
            15,
        )

    if pixel_variance < config.blank_variance_threshold or entropy < config.blank_entropy_threshold:
        _add_issue(
            result,
            "Image appears blank or contains too little visual detail.",
            "Ensure the crop leaf occupies most of the frame.",
            45,
            blocking=pixel_variance < 3.0 or entropy < 0.5,
        )

    result["quality_score"] = int(max(0, min(100, result["quality_score"])))
    result["status"] = "Invalid" if result["is_blocking"] else _status_from_score(result["quality_score"])
    result["passed"] = not result["warnings"] and not result["is_blocking"]
    return result


def safe_validate_image_quality(image: np.ndarray) -> Tuple[Dict[str, Any], bool]:
    """
    Validate image quality without allowing validator failures to break inference.

    Returns (validation_result, fallback_used).
    """
    try:
        return validate_image_quality(image), False
    except Exception as exc:
        result = _base_result()
        result.update(
            {
                "passed": True,
                "status": "Unknown",
                "warnings": ["Image quality validation could not be completed."],
                "suggestions": ["Continue analysis, or re-upload if the image looks unclear."],
                "metrics": {"validation_error": str(exc)},
                "quality_score": 70,
                "is_blocking": False,
            }
        )
        return result, True
