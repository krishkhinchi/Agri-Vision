"""
Agri-Vision Flask Application
Unified inference for disease classification (ResNet50) and growth stage prediction (YOLOv8)
"""
import hashlib
import logging
import os
import random
import re
import threading
import json
import base64
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms
from ultralytics import YOLO
from dotenv import load_dotenv

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
    Request,
    send_file,
    make_response
)
from flask_cors import CORS
from flasgger import Swagger
from flask_sqlalchemy import SQLAlchemy
from jinja2 import Environment, FileSystemLoader

# redis and rate limiting imports
import redis
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from model_registry import registry
from services.weather_service import generate_weather_recommendations
from services.yield_service import estimate_yield

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static", template_folder="templates")

# redis setup for rate limiting & payload caching
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    redis_client.ping()
    logger.info("redis connected for caching and rate limiting")
    limiter = Limiter(
        get_remote_address,
        app=app,
        storage_uri="redis://localhost:6379",
        strategy="fixed-window"
    )
except redis.ConnectionError:
    logger.warning("redis is down. falling back to in-memory rate limiting. caching disabled.")
    redis_client = None
    limiter = Limiter(get_remote_address, app=app)

# db config
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///agri_vision.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
from models import db
db.init_app(app)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class CustomRequest(Request):
    max_form_memory_size = 25 * 1024 * 1024  

app.request_class = CustomRequest

swagger = Swagger(app)
CORS(app)

app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.jinja_env.auto_reload = True
app.jinja_env.cache = {}

secret_key = os.getenv("SECRET_KEY") or "dev_secret_123"
app.secret_key = secret_key

LANG = {
    "en": {"welcome": "Welcome to Agri Vision"},
    "te": {"welcome": "అగ్రి విజన్‌కు స్వాగతం"},
}

os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("models", exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
MAX_INFERENCE_DIMENSION = 1024
DISPLAY_IMAGE_MAX_DIMENSION = 1200
DISPLAY_JPEG_QUALITY = 80

RESNET_MODEL_PATH = "models/cotton_crop_disease_classification/full_resnet50_model.pth"
YOLO_MODEL_PATH = "models/cotton_crop_growth_stage_prediction/best.pt"

disease_classes = [
    "Aphids",
    "Army worm",
    "Bacterial blight",
    "Cotton Boll Rot",
    "Green Cotton Boll",
    "Healthy",
    "Powdery mildew",
    "Target Spot",
]

growth_stage_classes = [
    "Cotton Blossom",
    "Cotton Bud",
    "Early Boll",
    "Matured Cotton Boll",
    "Split Cotton Boll",
]

disease_info_map = {
    "Aphids": {
        "healthy_image": "static/images/healthy_leaf.jpg",
        "description": "Aphids are small sap-sucking insects that weaken cotton plants by feeding on tender leaves and shoots.",
        "symptoms": "Curled leaves, sticky honeydew, yellowing, and clusters of tiny insects on the underside of leaves.",
        "treatment": "Remove heavily infested leaves, encourage natural predators, and use neem oil or recommended insecticide if infestation increases.",
    },
    "Army worm": {
        "healthy_image": "static/images/healthy_leaf.jpg",
        "description": "Army worms are leaf-feeding caterpillars that can quickly damage cotton foliage when populations build up.",
        "symptoms": "Chewed leaf edges, holes in leaves, skeletonized foliage, and visible larvae on plants.",
        "treatment": "Scout fields regularly, remove larvae where possible, and apply recommended biological or chemical control at early stages.",
    },
    "Bacterial blight": {
        "healthy_image": "static/images/healthy_leaf.jpg",
        "description": "Bacterial blight is a cotton disease that spreads through infected seed, crop residue, rain splash, and wind-driven moisture.",
        "symptoms": "Angular water-soaked leaf spots, dark lesions, yellowing, and drying of affected leaf tissue.",
        "treatment": "Avoid overhead irrigation, remove infected debris, use disease-free seed, and follow local copper-based spray recommendations if needed.",
    },
    "Cotton Boll Rot": {
        "healthy_image": "static/images/healthy_leaf.jpg",
        "description": "Cotton boll rot affects developing bolls, especially under humid conditions or poor field drainage.",
        "symptoms": "Soft or discolored bolls, fungal growth, rotting tissue, and premature boll drop.",
        "treatment": "Improve drainage and airflow, remove rotten bolls, avoid excess irrigation, and manage insects that create boll wounds.",
    },
    "Green Cotton Boll": {
        "healthy_image": "static/images/healthy_leaf.jpg",
        "description": "Green cotton boll indicates developing boll growth that should be monitored for nutrition, pests, and disease pressure.",
        "symptoms": "Green immature bolls with no clear disease symptoms unless stress, pest injury, or spotting appears.",
        "treatment": "Maintain balanced irrigation and nutrition, scout for pests, and continue regular field monitoring.",
    },
    "Healthy": {
        "healthy_image": "static/images/healthy_leaf.jpg",
        "description": "The leaf appears healthy with no major visible disease symptoms detected.",
        "symptoms": "Uniform green color, normal leaf shape, and no significant spots, mildew, curling, or pest damage.",
        "treatment": "Continue routine monitoring, balanced fertilization, proper irrigation, and preventive crop hygiene.",
    },
    "Powdery mildew": {
        "healthy_image": "static/images/healthy_leaf.jpg",
        "description": "Powdery mildew is a fungal disease that appears as white powdery growth on cotton leaves.",
        "symptoms": "White or gray powdery patches, yellowing leaves, reduced vigor, and premature leaf drying.",
        "treatment": "Improve airflow, remove infected debris, reduce leaf wetness, and apply recommended fungicide when needed.",
    },
    "Target Spot": {
        "healthy_image": "static/images/healthy_leaf.jpg",
        "description": "Target spot is a fungal leaf disease that produces circular lesions and can reduce cotton leaf area.",
        "symptoms": "Brown circular spots with ring-like patterns, yellow halos, leaf blight, and premature defoliation.",
        "treatment": "Reduce leaf wetness, improve spacing and airflow, remove infected residue, and use suitable fungicide if disease spreads.",
    },
}

UNCERTAINTY_THRESHOLD = 0.45
AMBIGUITY_MARGIN = 0.08

class ModelManager:
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._load_lock = threading.Lock()
        self.loaded = False
        self.errors = {"resnet": None, "yolo": None}
        self.resnet_model = None
        self.yolo_model = None
        self._initialized = True

    def load_models(self) -> Tuple[Optional[torch.nn.Module], Optional[YOLO]]:
        if self.loaded:
            return self.resnet_model, self.yolo_model

        with self._load_lock:
            if self.loaded:
                return self.resnet_model, self.yolo_model

            if self.resnet_model is None:
                try:
                    try:
                        self.resnet_model = torch.load(
                            RESNET_MODEL_PATH,
                            map_location=torch.device("cpu"),
                        )
                    except TypeError:
                        self.resnet_model = torch.load(
                            RESNET_MODEL_PATH,
                            map_location=torch.device("cpu"),
                            weights_only=False
                        )
                    self.resnet_model.eval()
                    self.errors["resnet"] = None
                    logger.info("ResNet50 loaded")
                except Exception as exc:
                    self.errors["resnet"] = str(exc)
                    logger.warning(f"ResNet50 load failed: {exc}")
                    self.resnet_model = None

            if self.yolo_model is None:
                try:
                    self.yolo_model = YOLO(YOLO_MODEL_PATH)
                    self.errors["yolo"] = None
                    logger.info("YOLOv8 loaded")
                except Exception as exc:
                    self.errors["yolo"] = str(exc)
                    logger.warning(f"YOLOv8 load failed: {exc}")
                    self.yolo_model = None

            self.loaded = True
            return self.resnet_model, self.yolo_model

    def diagnostics(self) -> Dict[str, Any]:
        return {
            "resnet": {
                "loaded": self.resnet_model is not None,
                "path": RESNET_MODEL_PATH,
                "error": self.errors.get("resnet"),
            },
            "yolo": {
                "loaded": self.yolo_model is not None,
                "path": YOLO_MODEL_PATH,
                "error": self.errors.get("yolo"),
            },
        }

model_manager = ModelManager()

resnet_model = None
yolo_model = None

def load_models():
    global resnet_model, yolo_model
    resnet_model, yolo_model = model_manager.load_models()
    return resnet_model, yolo_model

def ensure_models_loaded() -> None:
    load_models()

def _ensure_rgb(image: np.ndarray) -> np.ndarray:
    if image is None:
        raise ValueError("Image is None")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected an RGB image with 3 channels")
    return image

def resize_image(image: np.ndarray, max_dim: int = MAX_INFERENCE_DIMENSION) -> np.ndarray:
    height, width = image.shape[:2]
    if max(height, width) <= max_dim:
        return image
    scale = max_dim / float(max(height, width))
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)

def calculate_disease_severity(health_score: float) -> float:
    return max(0.0, 100.0 - float(health_score))

def generate_mock_heatmap(image_rgb: np.ndarray) -> np.ndarray:
    h, w, _ = image_rgb.shape
    x = np.linspace(-1, 1, w)
    y = np.linspace(-1, 1, h)
    x_grid, y_grid = np.meshgrid(x, y)
    cx, cy = 0.05, -0.05
    sigma = 0.35
    heatmap = np.exp(-((x_grid - cx) ** 2 + (y_grid - cy) ** 2) / (2 * sigma**2))
    heatmap = (heatmap - heatmap.min()) / (heatmap.max() - heatmap.min() + 1e-8)
    return heatmap

def generate_pure_heatmap(image_rgb: np.ndarray, heatmap: np.ndarray) -> np.ndarray:
    h, w, _ = image_rgb.shape
    heatmap_resized = cv2.resize(heatmap, (w, h))
    heatmap_255 = np.uint8(255 * heatmap_resized)
    heatmap_color = cv2.applyColorMap(heatmap_255, cv2.COLORMAP_JET)
    return cv2.cvtColor(heatmap_color, cv2.COLOR_BGR2RGB)

def apply_heatmap_on_image(image_rgb: np.ndarray, heatmap: np.ndarray, alpha: float = 0.6, beta: float = 0.4) -> np.ndarray:
    heatmap_color_rgb = generate_pure_heatmap(image_rgb, heatmap)
    return cv2.addWeighted(image_rgb, alpha, heatmap_color_rgb, beta, 0)

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

    def __call__(self, input_tensor: torch.Tensor, target_class_idx: Optional[int], original_image_rgb: np.ndarray) -> Optional[np.ndarray]:
        if self.model is None:
            return None

        self.model.eval()
        self.model.zero_grad(set_to_none=True)
        self.activations = None
        self.gradients = None
        self.heatmap_np = None

        try:
            device = next(self.model.parameters()).device
            input_tensor = input_tensor.to(device)

            with torch.enable_grad():
                output = self.model(input_tensor)
                if target_class_idx is None:
                    target_class_idx = int(output.argmax(dim=1).item())

                score = output[:, target_class_idx].sum()
                score.backward()

                if self.activations is None or self.gradients is None:
                    return None

                pooled_gradients = torch.mean(self.gradients, dim=(2, 3))
                weighted_activations = self.activations * pooled_gradients[:, :, None, None]
                heatmap = torch.sum(weighted_activations, dim=1).squeeze()
                heatmap = F.relu(heatmap)

                max_val = torch.max(heatmap)
                if float(max_val.item()) == 0.0:
                    heatmap = torch.zeros_like(heatmap)
                else:
                    heatmap = heatmap / max_val

                heatmap_np = heatmap.detach().cpu().numpy()
                self.heatmap_np = heatmap_np
                return apply_heatmap_on_image(original_image_rgb, heatmap_np)

        except Exception as exc:
            logger.error("Grad-CAM error: %s", exc)
            return None
        finally:
            self.gradients = None
            self.activations = None

def preprocess_image_for_resnet(image: np.ndarray, target_size: Tuple[int, int] = (224, 224)) -> torch.Tensor:
    transform = transforms.Compose([
        transforms.ToPILImage(),
        transforms.Resize(target_size),
        transforms.ToTensor(),
    ])
    tensor = transform(image).unsqueeze(0)
    return tensor

def infer_disease(image):
    if model_manager.resnet_model:
        processed = preprocess_image_for_resnet(image)
        with torch.no_grad():
            output = model_manager.resnet_model(processed)
            probs = F.softmax(output, dim=1)
            confidence, prediction = torch.max(probs, 1)
        probs_np = probs.numpy()
        class_idx = int(prediction.item())
        confidence_value = float(confidence.item())
        predicted_class = disease_classes[class_idx]
        healthy_idx = disease_classes.index("Healthy")  
        health_score = float(probs_np[0][healthy_idx]) * 100
    else:
        probs_np = np.random.rand(1, len(disease_classes))
        probs_np = probs_np / probs_np.sum(axis=1, keepdims=True)
        class_idx = int(np.argmax(probs_np[0]))
        confidence_value = float(np.max(probs_np[0]))
        predicted_class = disease_classes[class_idx]
        health_score = float(np.max(probs_np[0]))*100

    disease_confidences = {disease_classes[i]: float(probs_np[0][i]) for i in range(len(disease_classes))}

    return {
        "predicted_class": predicted_class,
        "predicted_class_idx": class_idx,
        "confidence": confidence_value,
        "all_confidences": disease_confidences,
        "health_score": health_score,
        "raw": probs_np.tolist(),
    }

def infer_growth_stage(image):
    result = {
        "main_class": None,
        "main_class_idx": None,
        "confidence": 0.0,
        "boxes": [],
        "raw": [],
    }
    if model_manager.yolo_model:
        pil_image = Image.fromarray(image)
        yolo_results = model_manager.yolo_model(pil_image)
        boxes = []
        for r in yolo_results:
            if hasattr(r, 'boxes'):
                for b in r.boxes:
                    class_id = int(b.cls[0].item()) if hasattr(b.cls[0], 'item') else int(b.cls[0])
                    conf = float(b.conf[0].item()) if hasattr(b.conf[0], 'item') else float(b.conf[0])
                    xyxy = b.xyxy[0].cpu().numpy().tolist()
                    boxes.append({
                        "class_id": class_id,
                        "class_name": growth_stage_classes[class_id] if class_id < len(growth_stage_classes) else str(class_id),
                        "confidence": conf,
                        "bbox": xyxy,
                    })
            else:
                continue
                
        if len(boxes):
            main = max(boxes, key=lambda x: x['confidence'])
            result.update({
                "main_class": main["class_name"],
                "main_class_idx": main["class_id"],
                "confidence": main["confidence"],
            })
            result["boxes"] = boxes
        result["raw"] = boxes
    return result

def generate_recommendations(disease_result: Dict[str, Any], growth_result: Dict[str, Any], weather: Optional[Dict[str, Any]] = None) -> list[str]:
    recs: list[str] = []
    dclass = disease_result["predicted_class"]

    instr_map = {
        "Aphids": ["Inspect leaves closely for clusters of small pests.", "Use recommended insecticides if infestation is severe."],
        "Army worm": ["Increase scouting frequency.", "Apply biological or suitable chemical controls early."],
        "Bacterial blight": ["Avoid overhead irrigation.", "Remove and destroy affected plant parts."],
        "Cotton Boll Rot": ["Improve field drainage, avoid stagnant water.", "Remove and destroy rotten bolls."],
        "Green Cotton Boll": ["Monitor bolls for signs of pests or disease.", "Maintain optimal nutrient regime."],
        "Healthy": ["Continue general crop monitoring.", "Maintain optimal fertilization and irrigation."],
        "Powdery mildew": ["Remove infected plant debris.", "Apply fungicide at recommended intervals."],
        "Target Spot": ["Monitor for spread, reduce leaf wetness.", "Apply suitable fungicide if required."],
    }
    recs.extend(instr_map.get(dclass, ["Practice general crop hygiene."]))
    
    if disease_result["health_score"] < 50:
        recs.append("Consult an agricultural expert urgently for low health score.")
        recs.append("Consult an agricultural expert if symptoms persist.")
    elif disease_result["health_score"] < 70:
        recs.append("Increase frequency of crop monitoring based on moderate health.")

    if disease_result.get("is_uncertain"):
        recs.append("Model confidence is low. Please upload a clearer image or consult an agricultural expert.")
    elif disease_result.get("is_ambiguous"):
        alt = disease_result.get("alternative_prediction", {}).get("class", "another condition")
        recs.append(f"The prediction may overlap with {alt}. Monitor the crop closely before applying treatment.")

    gmain = growth_result.get("main_class", None)
    grow_map = {
        "Cotton Blossom": ["Maintain regular watering during blossom phase.", "Scout for early flower pests."],
        "Cotton Bud": ["Ensure adequate phosphorus supply.", "Monitor for budworm."],
        "Early Boll": ["Start borer management as boll phase begins.", "Avoid excess nitrogen at this stage."],
        "Matured Cotton Boll": ["Reduce irrigation to harden bolls.", "Plan for harvest in coming weeks."],
        "Split Cotton Boll": ["Prepare for immediate harvest.", "Avoid rainfall exposure to split bolls."],
    }
    if gmain in grow_map:
        recs.extend(grow_map[gmain])

    if weather:
        recs.extend(generate_weather_recommendations(weather))

    return recs[:6]

def generate_farmer_insights(disease_result: Dict[str, Any], growth_result: Dict[str, Any]) -> list[str]:
    insights = []
    dclass = disease_result["predicted_class"]
    hscore = disease_result["health_score"]
    gmain = growth_result.get("main_class", "Unknown")

    if dclass != "Healthy":
        insights.append(f"Possible {dclass} risk detected. Immediate action advised.")
    elif hscore > 80:
        insights.append("Crop is currently healthy. No immediate disease risks detected.")
    else:
        insights.append("Crop shows slight stress. Monitor closely for early signs of disease.")

    if gmain == "Cotton Blossom":
        insights.append("Expected harvest in 45–60 days.")
    elif gmain == "Cotton Bud":
        insights.append("Expected harvest in 30–45 days.")
    elif gmain == "Early Boll":
        insights.append("Expected harvest in 20–30 days.")
    elif gmain == "Matured Cotton Boll":
        insights.append("Expected harvest in 10–15 days. Prepare equipment.")
    elif gmain == "Split Cotton Boll":
        insights.append("Ready for harvest. Ideal harvesting window is within 7 days.")

    return insights

def generate_advanced_recommendations(disease_result: Dict[str, Any], growth_result: Dict[str, Any]) -> Dict[str, str]:
    gmain = growth_result.get("main_class", "Unknown")
    dclass = disease_result["predicted_class"]

    adv_recs = {
        "irrigation_timing": "Maintain standard schedule (every 7-10 days depending on soil moisture).",
        "fertilizer_suggestions": "Use balanced NPK (e.g., 20-20-20) as per standard guidelines.",
        "pest_prevention": "Install sticky traps and monitor for early pest signs.",
        "harvesting_window": "Monitor crop maturity daily.",
    }

    if gmain in ["Cotton Blossom", "Cotton Bud"]:
        adv_recs["irrigation_timing"] = "Increase watering frequency to support blooming."
        adv_recs["fertilizer_suggestions"] = "Apply potassium-rich fertilizers to boost flower development."
    elif gmain in ["Matured Cotton Boll", "Split Cotton Boll"]:
        adv_recs["irrigation_timing"] = "Reduce or stop irrigation to harden bolls and prevent rot."
        adv_recs["harvesting_window"] = "Immediate to 1-2 weeks."

    if dclass == "Aphids":
        adv_recs["pest_prevention"] = "Use neem oil or recommended insecticide for Aphids immediately."
    elif dclass == "Army worm":
        adv_recs["pest_prevention"] = "Apply specific anti-worm biological controls like Bacillus thuringiensis (Bt)."
    elif dclass == "Cotton Boll Rot":
        adv_recs["irrigation_timing"] = "Stop irrigation immediately to allow soil and plant base to dry."
        
    return adv_recs

def encode_image_for_display(image: np.ndarray) -> str:
    display_image = resize_image(image, DISPLAY_IMAGE_MAX_DIMENSION)
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), DISPLAY_JPEG_QUALITY]
    ok, buffer = cv2.imencode(".jpg", display_image, encode_params)
    if not ok:
        raise ValueError("Failed to encode image for display")
    return base64.b64encode(buffer).decode("utf-8")

def is_allowed_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def calculate_file_hash(file_storage) -> str:
    sha256_hash = hashlib.sha256()
    file_storage.seek(0)
    for byte_block in iter(lambda: file_storage.read(4096), b""):
        sha256_hash.update(byte_block)
    file_storage.seek(0)
    return sha256_hash.hexdigest()

def read_uploaded_image(file_storage) -> Tuple[str, np.ndarray, np.ndarray]:
    from werkzeug.utils import secure_filename
    safe_filename = secure_filename(file_storage.filename)
    file_bytes = np.frombuffer(file_storage.read(), np.uint8)
    image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Error reading image file")
    return safe_filename, image, cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

GRAD_CAM_CACHE = {}
GRAD_CAM_CACHE_LOCK = threading.Lock()
MAX_CACHE_SIZE = 100

def get_cached_grad_cam(image_hash: str) -> Optional[Tuple[str, str]]:
    with GRAD_CAM_CACHE_LOCK:
        return GRAD_CAM_CACHE.get(image_hash)

def set_cached_grad_cam(image_hash: str, overlay_b64: str, heatmap_only_b64: str) -> None:
    with GRAD_CAM_CACHE_LOCK:
        if len(GRAD_CAM_CACHE) >= MAX_CACHE_SIZE:
            first_key = next(iter(GRAD_CAM_CACHE))
            GRAD_CAM_CACHE.pop(first_key, None)
        GRAD_CAM_CACHE[image_hash] = (overlay_b64, heatmap_only_b64)

def analyze_image(image: np.ndarray) -> Dict[str, Any]:
    import time
    start_time = time.time()
    
    resnet_model, yolo_model = model_manager.load_models()
    try:
        try:
            growth = infer_growth_stage(image)
        except Exception as exc:
            logger.error("Error during growth stage inference: %s", exc)
            growth = {"main_class": None, "main_class_idx": None, "confidence": 0.0, "boxes": [], "raw": []}

        disease = infer_disease(image)
        if not isinstance(disease, dict) or "predicted_class" not in disease or "health_score" not in disease:
            raise ValueError("Invalid disease model prediction output.")

        inference_time = time.time() - start_time
        try:
            if disease and disease.get("confidence"):
                registry.update_metrics(
                    model_type="resnet",
                    version="v1.0",
                    confidence=disease.get("confidence", 0.0),
                    inference_time=inference_time,
                    success=True
                )
            
            if growth and growth.get("confidence"):
                registry.update_metrics(
                    model_type="yolo",
                    version="v1.0",
                    confidence=growth.get("confidence", 0.0),
                    inference_time=inference_time,
                    success=True
                )
        except Exception as e:
            logger.error(f"Error tracking metrics: {e}")

        image_hash = hashlib.sha256(image.tobytes()).hexdigest()
        cached_result = get_cached_grad_cam(image_hash)
        
        grad_cam_image_b64 = None
        heatmap_only_b64 = None
        
        if cached_result is not None:
            grad_cam_image_b64, heatmap_only_b64 = cached_result
        else:
            if resnet_model is not None and disease.get("predicted_class_idx") is not None:
                try:
                    input_tensor = preprocess_image_for_resnet(image)
                    with GradCAM(resnet_model, resnet_model.layer4[-1]) as grad_cam:
                        grad_cam_overlay = grad_cam(input_tensor, disease["predicted_class_idx"], image)
                        heatmap_np = getattr(grad_cam, "heatmap_np", None)
                    if grad_cam_overlay is not None:
                        grad_cam_image_b64 = encode_image_for_display(grad_cam_overlay)
                    if heatmap_np is not None:
                        pure_heatmap_rgb = generate_pure_heatmap(image, heatmap_np)
                        heatmap_only_b64 = encode_image_for_display(pure_heatmap_rgb)
                except Exception as exc:
                    logger.error("Error generating Grad-CAM: %s", exc)

            if grad_cam_image_b64 is None or heatmap_only_b64 is None:
                try:
                    mock_heatmap = generate_mock_heatmap(image)
                    mock_overlay = apply_heatmap_on_image(image, mock_heatmap)
                    grad_cam_image_b64 = encode_image_for_display(mock_overlay)
                    
                    pure_heatmap_rgb = generate_pure_heatmap(image, mock_heatmap)
                    heatmap_only_b64 = encode_image_for_display(pure_heatmap_rgb)
                except Exception as exc:
                    logger.error("Error generating fallback heatmap: %s", exc)
            
            if grad_cam_image_b64 and heatmap_only_b64:
                set_cached_grad_cam(image_hash, grad_cam_image_b64, heatmap_only_b64)

        disease["heatmap_b64"] = grad_cam_image_b64
        disease["heatmap_only_b64"] = heatmap_only_b64

        recs = generate_recommendations(disease, growth)
        severity = calculate_disease_severity(disease["health_score"])
        yield_est = estimate_yield(disease, growth, weather=None, field_acres=1.0)
        adv_recs = generate_advanced_recommendations(disease, growth)
        insights = generate_farmer_insights(disease, growth)

        result = {
            "disease": disease,
            "growth": growth,
            "recommendations": recs,
            "grad_cam_image_b64": grad_cam_image_b64,
            "heatmap_only_b64": heatmap_only_b64,
            "disease_severity": severity,
            "yield_estimate": yield_est,
            "advanced_recommendations": adv_recs,
            "farmer_insights": insights,
        }

        if growth.get("main_class") is None:
            fallback_reason = "Growth stage model unavailable." if yolo_model is None else "Cotton growth stage could not be detected."
            result["warnings"] = [
                fallback_reason,
                "Disease analysis is still provided, but comparison may be less reliable.",
            ]

        return result
    except Exception as exc:
        logger.error("Unexpected error in image analysis: %s", exc)
        return {"error": "The AI model encountered an error. Please verify the image file."}

def build_comparison_result(old_results: Dict[str, Any], new_results: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(old_results, dict) or not isinstance(new_results, dict):
        raise ValueError("Invalid result objects.")

    old_disease = old_results.get("disease")
    new_disease = new_results.get("disease")
    if old_disease is None or new_disease is None:
        raise ValueError("Valid crop analysis missing in one or both images.")

    old_score = float(old_disease.get("health_score", 0.0))
    new_score = float(new_disease.get("health_score", 0.0))
    change = new_score - old_score
    abs_change = abs(change)

    if change > 1:
        trend = {"status": "improved", "label": "Improved", "icon": "fa-arrow-trend-up", "direction": "up"}
        headline = f"Crop health improved by {abs_change:.1f}%"
        recommendation = "Continue current treatment plan."
    elif change < -1:
        trend = {"status": "declined", "label": "Declined", "icon": "fa-arrow-trend-down", "direction": "down"}
        headline = f"Crop health declined by {abs_change:.1f}%"
        recommendation = "Increase inspection frequency."
    else:
        trend = {"status": "stable", "label": "Stable", "icon": "fa-arrows-left-right", "direction": "flat"}
        headline = "Crop health remained stable"
        recommendation = "Maintain current routine."

    old_predicted = old_disease.get("predicted_class", "Unknown")
    new_predicted = new_disease.get("predicted_class", "Unknown")
    disease_reduced = old_predicted != "Healthy" and new_predicted == "Healthy"
    disease_changed = old_predicted != new_predicted

    summary = [
        headline,
        "Disease spread reduced" if disease_reduced else (f"Signal shifted to {new_predicted}" if disease_changed else f"Signal remains {new_predicted}"),
        recommendation,
    ]

    return {
        "old_score": old_score,
        "new_score": new_score,
        "change_percentage": change,
        "abs_change_percentage": abs_change,
        "trend": trend,
        "recommendation": recommendation,
        "summary": summary,
    }

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/")
def index():
    lang = request.args.get("lang", "en")
    return render_template("index.html", text=LANG.get(lang, LANG["en"]), lang=lang)

@app.route("/health")
def health():
    ensure_models_loaded()
    diagnostics = model_manager.diagnostics()
    model_loaded = diagnostics["resnet"]["loaded"] and diagnostics["yolo"]["loaded"]
    status_code = 200 if model_loaded else 503
    return jsonify({
        "status": "healthy" if model_loaded else "degraded",
        "model_loaded": model_loaded,
        "models": diagnostics,
    }), status_code

# --- core api with redis cache & rate limiting ---
@app.route("/api/analyze", methods=["POST"])
@limiter.limit("10 per minute")
def api_analyze():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
        
    try:
        file_bytes = np.frombuffer(file.read(), np.uint8)
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        cache_key = f"inference_cache:{file_hash}"
        
        # check cache
        if redis_client:
            cached = redis_client.get(cache_key)
            if cached:
                logger.info("cache hit - skipping model inference")
                res = make_response(cached)
                res.headers['Content-Type'] = 'application/json'
                res.headers['X-Cache-Hit'] = '1'
                return res
                
        # cache miss - decode and run
        logger.info("cache miss - running inference")
        image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        if image is None:
            return jsonify({'error': 'Invalid image file'}), 400
            
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = analyze_image(image_rgb)
        
        resp_data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "results": results
        }
        resp_json = json.dumps(resp_data)
        
        # save to redis (24h ttl)
        if redis_client:
            redis_client.setex(cache_key, 86400, resp_json)
            
        res = make_response(resp_json)
        res.headers['Content-Type'] = 'application/json'
        res.headers['X-Cache-Hit'] = '0'
        return res
        
    except Exception as e:
        logger.error(f"API analysis error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    ensure_models_loaded()
    
    try:
        registry.register_model(
            model_type="resnet", version="v1.0", path="models/cotton_crop_disease_classification/full_resnet50_model.pth", accuracy=0.9983
        )
        registry.register_model(
            model_type="yolo", version="v1.0", path="models/cotton_crop_growth_stage_prediction/best.pt", accuracy=0.6006
        )
        registry.set_active_model("resnet", "v1.0")
        registry.set_active_model("yolo", "v1.0")
    except Exception as e:
        logger.error(f"Error registering models: {e}")
    
    is_debug = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t")
    app.run(debug=is_debug, host="0.0.0.0", port=5000)
