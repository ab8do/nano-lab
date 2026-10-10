"""
Dino controller: raise your hand in front of the webcam to make the dino jump.

Pipeline: webcam -> mirrored frame -> MediaPipe Hands (21 landmarks)
          -> "raised" test -> one byte 'J' over USB serial (9600 baud).

Install:  pip install -r requirements.txt
Run:      python dino_controller.py        (press q in the camera window to quit)
"""
import time

import cv2
import mediapipe as mp
import serial

PORT = "COM3"          # Arduino port (Windows: COMx, Linux: /dev/ttyUSB0, macOS: /dev/cu.usbserial-*)
BAUD = 9600            # must match Serial.begin(9600) in dino_game.ino
RAISE_MARGIN = 0.2     # index fingertip must be this much (fraction of image height) above the wrist

try:
    arduino = serial.Serial(PORT, BAUD, timeout=0.1)
    time.sleep(2)      # the Nano resets when the port is opened
    print("Connected to Arduino!")
except Exception as e:
    print(f"Error connecting to Serial: {e}")
    raise SystemExit

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
mp_draw = mp.solutions.drawing_utils

cap = cv2.VideoCapture(0)
raised_prev = False

try:
    while cap.isOpened():
        ok, frame = cap.read()
        if not ok:
            break

        frame = cv2.flip(frame, 1)                      # mirror image: natural left/right
        results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        raised = False
        if results.multi_hand_landmarks:
            for lm in results.multi_hand_landmarks:
                mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)
                tip_y = lm.landmark[mp_hands.HandLandmark.INDEX_FINGER_TIP].y
                wrist_y = lm.landmark[mp_hands.HandLandmark.WRIST].y
                if tip_y < wrist_y - RAISE_MARGIN:      # image y grows downwards
                    raised = True

        if raised and not raised_prev:                  # rising edge only: no repeated jumps
            arduino.write(b"J")
            print("Jump / Restart signal sent")
        raised_prev = raised

        label = "JUMP!" if raised else "Waiting..."
        cv2.putText(frame, label, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("Hand gesture control for Dino", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
finally:
    cap.release()
    cv2.destroyAllWindows()
    arduino.close()
