import os

import cv2
import numpy as np
from celery import Celery

# Initialize Celery
celery = Celery(
    "agri_vision_tasks",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

# Import from app.py at the top (this is safe now)
from app import analyze_image, load_models, logger

# Load models once for the worker
load_models()


@celery.task(bind=True)
def process_inference_task(self, image_bytes_list):
    try:
        self.update_state(state="PROCESSING", meta={"status": "Analyzing image..."})
        file_bytes = np.array(image_bytes_list, dtype=np.uint8)
        image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        if image is None:
            return {"error": "Invalid image data"}

        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = analyze_image(image_rgb)
        return results

    except Exception as e:
        logger.error(f"Celery task failed: {e}")
        return {"error": str(e)}
