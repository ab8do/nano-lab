import math
import time
from collections import deque, Counter

import cv2
import mediapipe as mp
import serial

# ====== الاعدادات ======
PORT = 'COM3'      # غيّره الى منفذ الاردوينو عندك
BAUD = 57600       # يجب ان يطابق Serial.begin(57600) في الاردوينو
# ========================

try:
    arduino = serial.Serial(PORT, BAUD, timeout=0.01)
    time.sleep(2)  # انتظار اعادة تشغيل الاردوينو
    print("Connected to Arduino!")
except Exception as e:
    print(f"Error connecting to Serial: {e}")
    raise SystemExit

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(max_num_hands=1,
                       min_detection_confidence=0.7,
                       min_tracking_confidence=0.6)
mp_draw = mp.solutions.drawing_utils

cap = cv2.VideoCapture(0)

sx, sy = 50.0, 50.0            # موضع اليد بعد التنعيم (0-100)
history = deque(maxlen=5)      # للتصويت على عدد الاصابع وتقليل الارتعاش


def dist(pts, a, b):
    return math.hypot(pts[a].x - pts[b].x, pts[a].y - pts[b].y)


def count_fingers(pts):
    """يعد الاصابع المرفوعة (0-5) بغض النظر عن اتجاه اليد."""
    n = 0
    # الابهام: الطرف ابعد عن قاعدة الخنصر من المفصل
    if dist(pts, 4, 17) > dist(pts, 3, 17):
        n += 1
    # باقي الاصابع: الطرف ابعد عن المعصم من المفصل الاوسط
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        if dist(pts, tip, 0) > dist(pts, pip, 0):
            n += 1
    return n


def to_pct(v):
    """تحويل الاحداثي (0-1) الى 0-100 مع تضييق المدى لراحة اليد."""
    return int(max(0, min(100, (v - 0.15) / 0.70 * 100)))


print("اضغط q للخروج، و m للعودة الى القائمة")

while cap.isOpened():
    ok, frame = cap.read()
    if not ok:
        break

    frame = cv2.flip(frame, 1)  # مرآة
    res = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    fingers = 9  # 9 = لا توجد يد
    if res.multi_hand_landmarks:
        lm = res.multi_hand_landmarks[0]
        mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)
        pts = lm.landmark

        # مركز الكف (قاعدة الاصبع الوسطى)
        tx, ty = to_pct(pts[9].x), to_pct(pts[9].y)
        sx += (tx - sx) * 0.6
        sy += (ty - sy) * 0.6

        history.append(count_fingers(pts))
        fingers = Counter(history).most_common(1)[0][0]
    else:
        history.clear()

    # الحزمة: [255][x][y][fingers]
    try:
        arduino.write(bytes([255, int(sx), int(sy), fingers]))
    except Exception as e:
        print(f"Serial write error: {e}")
        break

    txt = "No hand" if fingers == 9 else f"Fingers: {fingers}  X:{int(sx)} Y:{int(sy)}"
    cv2.putText(frame, txt, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.imshow("Gesture Games Controller", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('m'):
        arduino.write(bytes([254, ord('M')]))  # العودة للقائمة

cap.release()
cv2.destroyAllWindows()
arduino.close()
