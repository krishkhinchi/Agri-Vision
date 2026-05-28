"""Grad-CAM utilities for ResNet disease classification explainability."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

import cv2
import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


@dataclass
class GradCAMResult:
    available: bool
    status: str
    overlay_image: Optional[np.ndarray] = None
    heatmap_image: Optional[np.ndarray] = None
    overlay_path: Optional[str] = None
    heatmap_path: Optional[str] = None
    target_layer: str = "ResNet50 layer4[-1]"
    error: Optional[str] = None


def generate_pure_heatmap(image_rgb: np.ndarray, heatmap: np.ndarray) -> np.ndarray:
    height, width, _ = image_rgb.shape
    heatmap_resized = cv2.resize(heatmap, (width, height))
    heatmap_255 = np.uint8(255 * heatmap_resized)
    heatmap_color = cv2.applyColorMap(heatmap_255, cv2.COLORMAP_JET)
    return cv2.cvtColor(heatmap_color, cv2.COLOR_BGR2RGB)


def apply_heatmap_on_image(
    image_rgb: np.ndarray,
    heatmap: np.ndarray,
    alpha: float = 0.6,
    beta: float = 0.4,
) -> np.ndarray:
    heatmap_color_rgb = generate_pure_heatmap(image_rgb, heatmap)
    return cv2.addWeighted(image_rgb, alpha, heatmap_color_rgb, beta, 0)


def get_resnet_final_conv_layer(model: torch.nn.Module) -> torch.nn.Module:
    if not hasattr(model, "layer4"):
        raise AttributeError("Model does not expose ResNet layer4.")
    return model.layer4[-1]


class GradCAM:
    def __init__(self, model: torch.nn.Module, target_layer: torch.nn.Module):
        self.model = model
        self.target_layer = target_layer
        self.gradients = None
        self.activations = None
        self.heatmap_np = None
        self.forward_handle = self.target_layer.register_forward_hook(self._save_activation)
        self.backward_handle = self.target_layer.register_full_backward_hook(self._save_gradient)

    def cleanup(self) -> None:
        if getattr(self, "forward_handle", None) is not None:
            self.forward_handle.remove()
            self.forward_handle = None
        if getattr(self, "backward_handle", None) is not None:
            self.backward_handle.remove()
            self.backward_handle = None

    def __enter__(self) -> "GradCAM":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def _save_activation(self, module, inputs, output):
        self.activations = output.detach()

    def _save_gradient(self, module, grad_input, grad_output):
        if grad_output and grad_output[0] is not None:
            self.gradients = grad_output[0].detach()

    def __call__(
        self,
        input_tensor: torch.Tensor,
        target_class_idx: Optional[int],
        original_image_rgb: np.ndarray,
    ) -> Optional[np.ndarray]:
        if self.model is None:
            return None

        self.model.eval()
        self.model.zero_grad(set_to_none=True)
        self.activations = None
        self.gradients = None
        self.heatmap_np = None

        try:
            try:
                device = next(self.model.parameters()).device
            except StopIteration:
                device = torch.device("cpu")
            input_tensor = input_tensor.to(device)

            with torch.enable_grad():
                output = self.model(input_tensor)
                if target_class_idx is None:
                    target_class_idx = int(output.argmax(dim=1).item())

                score = output[:, target_class_idx].sum()
                score.backward()

                if self.activations is None or self.gradients is None:
                    logger.warning("Grad-CAM activations or gradients were not captured.")
                    return None

                pooled_gradients = torch.mean(self.gradients, dim=(2, 3))
                weighted_activations = self.activations * pooled_gradients[:, :, None, None]
                heatmap = torch.sum(weighted_activations, dim=1).squeeze()
                heatmap = F.relu(heatmap)

                max_val = torch.max(heatmap)
                if float(max_val.item()) > 0.0:
                    heatmap = heatmap / max_val
                else:
                    heatmap = torch.zeros_like(heatmap)

                self.heatmap_np = heatmap.detach().cpu().numpy()
                return apply_heatmap_on_image(original_image_rgb, self.heatmap_np)
        except Exception as exc:
            logger.exception("Grad-CAM generation failed: %s", exc)
            return None
        finally:
            self.gradients = None
            self.activations = None


def _save_rgb_image(image_rgb: np.ndarray, output_dir: str, filename: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    filesystem_path = os.path.join(output_dir, filename)
    cv2.imwrite(filesystem_path, cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR))
    return filesystem_path.replace("\\", "/")


def generate_gradcam_explanation(
    model: Optional[torch.nn.Module],
    input_tensor: torch.Tensor,
    image_rgb: np.ndarray,
    target_class_idx: Optional[int],
    output_dir: str = "static/generated/gradcam",
    filename_prefix: Optional[str] = None,
) -> GradCAMResult:
    if model is None:
        return GradCAMResult(available=False, status="unavailable", error="ResNet50 model is not loaded.")

    try:
        target_layer = get_resnet_final_conv_layer(model)
        prefix = filename_prefix or uuid4().hex

        with GradCAM(model, target_layer) as grad_cam:
            overlay = grad_cam(input_tensor, target_class_idx, image_rgb)
            heatmap_np = grad_cam.heatmap_np

        if overlay is None or heatmap_np is None:
            return GradCAMResult(
                available=False,
                status="failed",
                error="Grad-CAM did not produce an activation heatmap.",
            )

        heatmap_image = generate_pure_heatmap(image_rgb, heatmap_np)
        overlay_path = _save_rgb_image(overlay, output_dir, f"{prefix}_overlay.jpg")
        heatmap_path = _save_rgb_image(heatmap_image, output_dir, f"{prefix}_heatmap.jpg")

        return GradCAMResult(
            available=True,
            status="generated",
            overlay_image=overlay,
            heatmap_image=heatmap_image,
            overlay_path=overlay_path,
            heatmap_path=heatmap_path,
        )
    except Exception as exc:
        logger.exception("Grad-CAM explainability failed: %s", exc)
        return GradCAMResult(available=False, status="failed", error=str(exc))
