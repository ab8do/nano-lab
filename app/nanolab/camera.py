import sys


def open_camera(index: int = 0):
    import cv2
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError("camera")
    return cap
