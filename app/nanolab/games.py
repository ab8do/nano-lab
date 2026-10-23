from collections import Counter, deque

import cv2

from .camera import open_camera
from .engine import Engine
from .handtrack import HandTracker, count_fingers, draw_hand, to_pct
from .preview import PREVIEW


class GamesEngine(Engine):
    name = "Gesture Games"
    baud = 57600

    def run(self):
        cap = open_camera(self.cfg.get("camera", 0))
        tracker = HandTracker()
        sx = sy = 50.0
        history = deque(maxlen=5)
        try:
            while not self.stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError("camera")
                frame = cv2.flip(frame, 1)
                pts = tracker.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                fingers = 9                                         # 9 = no hand
                if pts:
                    draw_hand(frame, pts)
                    sx += (to_pct(pts[9].x) - sx) * 0.6             # palm centre, smoothed
                    sy += (to_pct(pts[9].y) - sy) * 0.6
                    history.append(count_fingers(pts))
                    fingers = Counter(history).most_common(1)[0][0]  # majority vote of 5 frames
                else:
                    history.clear()
                self.link.write(bytes([255, int(sx), int(sy), fingers]))
                self.info = {"fingers": fingers, "x": int(sx), "y": int(sy)}
                txt = "No hand" if fingers == 9 else f"Fingers: {fingers}"
                PREVIEW.set_frame(frame, txt)
        finally:
            tracker.close()
            cap.release()
            PREVIEW.clear()

    def command(self, name):
        if name == "menu" and self.link:
            self.link.write(bytes([254, ord("M")]))
