import math
import time
import urllib.request

from .config import APP_DIR
from .logbus import log
from .util import resource_path

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")

CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
               (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
               (18, 19), (19, 20), (0, 17)]


def model_path():
    bundled = resource_path("assets/hand_landmarker.task")
    if bundled.exists():
        return bundled
    local = APP_DIR / "hand_landmarker.task"
    if not local.exists():
        log("Downloading the hand model (about 8 MB, once)...")
        APP_DIR.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, local)
    return local


class HandTracker:
    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision
        self.mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path())),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.7,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.6,
        )
        self.landmarker = vision.HandLandmarker.create_from_options(options)
        self.t0 = time.time()
        self.last_ts = -1

    def detect(self, rgb):
        ts = int((time.time() - self.t0) * 1000)
        ts = ts if ts > self.last_ts else self.last_ts + 1     # timestamps must strictly increase
        self.last_ts = ts
        result = self.landmarker.detect_for_video(
            self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), ts)
        return result.hand_landmarks[0] if result.hand_landmarks else None

    def close(self):
        try:
            self.landmarker.close()
        except Exception:
            pass


def draw_hand(frame, pts):
    import cv2
    h, w = frame.shape[:2]
    xy = [(int(p.x * w), int(p.y * h)) for p in pts]
    for a, b in CONNECTIONS:
        cv2.line(frame, xy[a], xy[b], (0, 200, 255), 2)
    for p in xy:
        cv2.circle(frame, p, 4, (0, 255, 0), -1)


def _dist(pts, a, b):
    return math.hypot(pts[a].x - pts[b].x, pts[a].y - pts[b].y)


def count_fingers(pts):
    """Extended fingers (0-5), independent of hand orientation."""
    n = 1 if _dist(pts, 4, 17) > _dist(pts, 3, 17) else 0
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        if _dist(pts, tip, 0) > _dist(pts, pip, 0):
            n += 1
    return n


def to_pct(v):
    """0-1 image coordinate -> 0-100, using the central 70% of the image."""
    return int(max(0, min(100, (v - 0.15) / 0.70 * 100)))
