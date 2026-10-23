import threading
import time


class Preview:
    """Latest camera frame as JPEG, shared with the web page (MJPEG stream)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg = None
        self.stamp = 0
        self._last = 0.0

    def set_frame(self, frame, text=None):
        now = time.time()
        if now - self._last < 0.066:        # at most ~15 fps
            return
        self._last = now
        import cv2
        if text:
            cv2.putText(frame, text, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with self.lock:
                self.jpeg = buf.tobytes()
                self.stamp += 1

    def get(self):
        with self.lock:
            return self.jpeg, self.stamp

    def clear(self):
        with self.lock:
            self.jpeg = None
            self.stamp += 1


PREVIEW = Preview()
