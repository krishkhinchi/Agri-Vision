"""
tests/test_image_quality.py

Unit tests for image quality validation service.
"""

import numpy as np
from unittest.mock import patch

from services.image_quality import (
    validate_image_quality,
    safe_validate_image_quality,
)


class TestValidateImageQuality:
    """Tests for validate_image_quality()."""

    def test_valid_image_quality(self):
        """A normal image should return a structured result."""
        img = np.random.randint(
            0,
            256,
            (512, 512, 3),
            dtype=np.uint8
        )

        result = validate_image_quality(img)

        assert isinstance(result, dict)
        assert "quality_score" in result
        assert "status" in result
        assert result["is_blocking"] is False

    def test_none_image_is_invalid(self):
        """None image should be rejected."""
        result = validate_image_quality(None)

        assert result["status"] == "Invalid"
        assert result["is_blocking"] is True

    def test_low_resolution_warning(self):
        """Low resolution images should generate warnings."""
        img = np.ones((64, 64, 3), dtype=np.uint8) * 128

        result = validate_image_quality(img)

        assert len(result["warnings"]) > 0

    def test_blank_image_detection(self):
        """Blank images should be detected."""
        img = np.zeros((512, 512, 3), dtype=np.uint8)

        result = validate_image_quality(img)

        assert len(result["warnings"]) > 0
    
    def test_dark_image_warning(self):
        """Very dark images should trigger lighting warnings."""
        img = np.zeros((512, 512, 3), dtype=np.uint8)

        result = validate_image_quality(img)

        assert len(result["warnings"]) > 0

    def test_invalid_image_structure(self):
        """Unsupported image structures should be rejected."""
        img = np.array([1, 2, 3])

        result = validate_image_quality(img)

        assert result["status"] == "Invalid"
        assert result["is_blocking"] is True


class TestSafeValidateImageQuality:
    """Tests for safe_validate_image_quality()."""

    def test_safe_validator_success(self):
        """Wrapper should return normal result when validation succeeds."""
        img = np.random.randint(
            0,
            256,
            (512, 512, 3),
            dtype=np.uint8
        )
        result, fallback_used = safe_validate_image_quality(img)

        assert fallback_used is False
        assert isinstance(result, dict)

    def test_safe_validator_fallback(self):
        """Exceptions should trigger fallback handling."""

        img = np.random.randint(
            0, 256, (512, 512, 3), dtype=np.uint8
        )

        with patch(
            "services.image_quality.validate_image_quality",
            side_effect=RuntimeError("boom"),
        ):
            result, fallback_used = safe_validate_image_quality(img)

        assert fallback_used is True
        assert result["status"] == "Unknown"

