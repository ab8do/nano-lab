import cv2

from .camera import open_camera
from .engine import Engine
from .handtrack import HandTracker, draw_hand
from .logbus import log
from .preview import PREVIEW

RAISE_MARGIN = 0.2      # index fingertip must be this much (fraction of image height) above the wrist


class DinoEngine(Engine):
    name = "Dino"
    baud = 9600

    def run(self):
        cap = open_camera(self.cfg.get("camera", 0))
        tracker = HandTracker()
        raised_prev = False
        try:
            while not self.stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError("camera")
                frame = cv2.flip(frame, 1)
                pts = tracker.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                raised = False
                if pts:
                    draw_hand(frame, pts)
                    raised = pts[8].y < pts[0].y - RAISE_MARGIN     # image y grows downwards
                if raised and not raised_prev:                      # rising edge only
                    self.link.write(b"J")
                    log("Dino: jump signal sent")
                raised_prev = raised
                self.info = {"raised": raised, "hand": bool(pts)}
                PREVIEW.set_frame(frame, "JUMP!" if raised else "Waiting...")
        finally:
            tracker.close()
            cap.release()
            PREVIEW.clear()
