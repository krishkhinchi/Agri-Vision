
# Confidence Calibration and Uncertainty-Aware Predictions

This module adds:

- Temperature Scaling
- Expected Calibration Error (ECE)
- Confidence Buckets
- Warning Messages for low confidence predictions

File:
services/confidence_calibration.py

Example:

prediction = {
    "prediction": "Leaf Blight",
    "raw_confidence": 0.88,
    "calibrated_confidence": 0.76,
    "confidence_level": "medium_confidence"
}
