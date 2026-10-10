"""
وجه ذكي تفاعلي: مساعد صوتي بـ Gemini + وجه متحرك على شاشة الاردوينو

التثبيت:
    pip install google-genai sounddevice numpy opencv-python pyserial pydantic
    (اختياري كاحتياط للصوت: pip install pyttsx3)

التشغيل:
    1) ضع مفتاح Gemini في المتغير API_KEY بالاسفل (او في متغير البيئة GEMINI_API_KEY)
    2) غيّر PORT الى منفذ الاردوينو
    3) python voice_face_ai.py
"""

import base64
import io
import json
import os
import threading
import time
import wave
from collections import deque

import numpy as np
import serial
import sounddevice as sd
from google import genai
from google.genai import types
from pydantic import BaseModel

# ===================== الاعدادات =====================
API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_YOUR_KEY_HERE")
PORT = "COM3"        # منفذ الاردوينو
BAUD = 57600         # نفس Serial.begin(57600) في smart_face_v3.ino

# تتم تجربة النماذج بالترتيب، وان فشل الاول (حصة/اسم) ينتقل للتالي تلقائيا
CHAT_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-2.5-flash-preview-tts"]
VOICE = "Kore"       # اسم الصوت (جرّب: Puck, Aoede, Charon, Fenrir ...)

USE_CAMERA = True    # العينان تتبعان وجهك عبر كاميرا اللابتوب
SLEEP_AFTER = 90     # ثواني بلا صوت ولا وجه قبل ان ينعس
MIC_THRESHOLD = None # None = معايرة تلقائية. جرّب رقما مثل 800 اذا كان الميكروفون لا يلتقط/يلتقط كثيرا
# ======================================================

SYSTEM_PROMPT = """You are 'Robo', a tiny cheerful, witty robot whose face lives on a small OLED screen.
You hear the user through a microphone and you answer by voice.
Rules:
- Reply in the same language the user spoke (Arabic including Algerian Darija, French, or English).
- Keep replies short: one or two natural spoken sentences. No emojis, no markdown, no lists.
- Be warm, curious and playful, with a bit of personality.
Return JSON with exactly these fields:
  heard: transcript of what the user said, in the original language
  emotion: one of neutral, happy, sad, angry, surprised, love, sleepy, wink (matching your reply)
  reply: what you say out loud
If the audio has no clear human speech, return empty strings for heard and reply."""

EMOTION_CHAR = {"neutral": "n", "happy": "h", "sad": "s", "angry": "a",
                "surprised": "u", "love": "l", "sleepy": "z", "wink": "k"}


class FaceReply(BaseModel):
    heard: str
    emotion: str
    reply: str


if API_KEY == "PASTE_YOUR_KEY_HERE":
    print("ضع مفتاح Gemini في API_KEY اولا (او في متغير البيئة GEMINI_API_KEY)")
    raise SystemExit

client = genai.Client(api_key=API_KEY)

# ===================== الاتصال بالاردوينو =====================
try:
    arduino = serial.Serial(PORT, BAUD, timeout=0.01)
    time.sleep(2)
    print("Connected to Arduino!")
except Exception as e:
    print(f"Error connecting to Serial: {e}")
    raise SystemExit

ser_lock = threading.Lock()


def send(b: bytes):
    with ser_lock:
        try:
            arduino.write(b)
        except Exception as e:
            print("Serial error:", e)


def cmd(c: str):
    send(bytes([254, ord(c)]))


def gaze(x, y):
    send(bytes([255, int(max(0, min(100, x))), int(max(0, min(100, y)))]))


def mouth(level):
    send(bytes([253, int(max(0, min(100, level)))]))


# ===================== حالة عامة =====================
stop_event = threading.Event()
state = {"last_activity": time.time(), "asleep": False}


def touch():
    state["last_activity"] = time.time()


# ===================== الكاميرا: العينان تتبعان وجهك =====================
def camera_loop():
    import cv2
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("تعذر فتح الكاميرا، سيعمل الوجه بدون تتبع.")
        return
    last_seen = 0.0
    last_send = 0.0
    while not stop_event.is_set():
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1)
            continue
        small = cv2.resize(frame, (320, 240))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.2, 5, minSize=(40, 40))
        now = time.time()
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx, cy = (x + w / 2) / 320.0, (y + h / 2) / 240.0
            if now - last_send > 0.1:
                gaze((1 - cx) * 100, cy * 100)   # (1-cx): مرآة، فتنظر العينان نحوك
                last_send = now
            if now - last_seen > 8:               # شخص ظهر امام الكاميرا
                cmd("W")
                state["asleep"] = False
            last_seen = now
            touch()
        time.sleep(0.05)
    cap.release()


# ===================== الميكروفون =====================
RATE = 16000
BLOCK = 480  # 30ms
THRESH = 500.0


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float32) ** 2)))


def calibrate():
    global THRESH
    if MIC_THRESHOLD is not None:
        THRESH = float(MIC_THRESHOLD)
    else:
        print("معايرة ضجيج الغرفة (ثانية واحدة، لا تتكلم)...")
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK) as s:
            vals = [rms(s.read(BLOCK)[0][:, 0]) for _ in range(33)]
        noise = float(np.percentile(vals, 90))
        THRESH = max(noise * 3.0, 450.0)
    print(f"عتبة الصوت: {THRESH:.0f}")


def listen_once():
    """ينتظر كلامك ثم يعيد تسجيلك كاملا (ينتهي بعد ثانية صمت)."""
    pre = deque(maxlen=10)       # 0.3 ثانية قبل بدء الكلام
    frames = []
    speaking = False
    speech_blocks = 0
    silence_blocks = 0
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK) as stream:
        while not stop_event.is_set():
            data, _ = stream.read(BLOCK)
            chunk = data[:, 0].copy()
            level = rms(chunk)

            if not speaking:
                pre.append(chunk)
                speech_blocks = speech_blocks + 1 if level > THRESH else 0
                if speech_blocks >= 4:
                    speaking = True
                    frames = list(pre)
                    silence_blocks = 0
                    state["asleep"] = False
                    touch()
                    cmd("L")
                elif (time.time() - state["last_activity"] > SLEEP_AFTER) and not state["asleep"]:
                    cmd("z")
                    state["asleep"] = True
            else:
                frames.append(chunk)
                silence_blocks = 0 if level > THRESH * 0.6 else silence_blocks + 1
                if silence_blocks > 33 or len(frames) > 500:   # ثانية صمت او 15 ثانية
                    break
    if not frames:
        return None
    return np.concatenate(frames)


def to_wav(audio):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


# ===================== Gemini =====================
history = deque(maxlen=12)
_model_idx = {"chat": 0, "tts": 0}


def call_models(kind, models, fn):
    """يجرب النماذج بالترتيب ويتذكر النموذج الذي نجح."""
    last_err = None
    for i in range(len(models)):
        idx = (_model_idx[kind] + i) % len(models)
        try:
            result = fn(models[idx])
            _model_idx[kind] = idx
            return result
        except Exception as e:
            last_err = e
            print(f"[{models[idx]}] فشل: {str(e)[:150]}")
    raise last_err


def ask_gemini(wav_bytes):
    parts = [
        types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
        types.Part(text="(voice message from the user)"),
    ]
    contents = list(history) + [types.Content(role="user", parts=parts)]
    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_schema=FaceReply,
        temperature=0.9,
    )
    resp = call_models("chat", CHAT_MODELS,
                       lambda m: client.models.generate_content(model=m, contents=contents, config=cfg))
    try:
        data = json.loads(resp.text)
        heard = str(data.get("heard", "")).strip()
        emotion = str(data.get("emotion", "neutral")).strip().lower()
        reply = str(data.get("reply", "")).strip()
    except Exception:
        heard, emotion, reply = "", "neutral", (resp.text or "").strip()
    if heard and reply:
        history.append(types.Content(role="user", parts=[types.Part(text=heard)]))
        history.append(types.Content(role="model", parts=[types.Part(text=reply)]))
    return heard, emotion, reply


def decode_audio(data):
    """يقبل PCM خام (24kHz) او ملف WAV ويعيد (مصفوفة int16، معدل العينة)."""
    if isinstance(data, str):
        data = base64.b64decode(data)
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data), "rb") as w:
            rate, ch = w.getframerate(), w.getnchannels()
            arr = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if ch > 1:
            arr = arr[::ch]
        return arr, rate
    return np.frombuffer(data, dtype=np.int16), 24000


def synth(text):
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": VOICE}}},
    )
    resp = call_models("tts", TTS_MODELS,
                       lambda m: client.models.generate_content(model=m, contents=text, config=cfg))
    return decode_audio(resp.candidates[0].content.parts[0].inline_data.data)


def play_with_mouth(audio, rate):
    """يشغل الصوت ويرسل شدته للاردوينو ليتحرك الفم مع الكلام."""
    step = 0.05
    n = max(1, int(rate * step))
    levels = []
    for i in range(0, len(audio), n):
        seg = audio[i:i + n].astype(np.float32)
        levels.append(float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0)
    ref = max(float(np.percentile(levels, 90)), 1.0)
    sd.play(audio, rate)
    t0 = time.time()
    for k, lv in enumerate(levels):
        mouth(100 * lv / ref)
        wait = t0 + (k + 1) * step - time.time()
        if wait > 0:
            time.sleep(wait)
    sd.wait()
    mouth(0)


def fallback_tts(text):
    try:
        import pyttsx3
        eng = pyttsx3.init()
        eng.say(text)
        eng.runAndWait()
    except Exception as e:
        print("لا يوجد صوت احتياطي:", e)


def speak(text):
    cmd("S")
    try:
        audio, rate = synth(text)
        play_with_mouth(audio, rate)
    except Exception as e:
        print("فشل TTS من Gemini:", str(e)[:150])
        fallback_tts(text)
    finally:
        cmd("I")


# ===================== البرنامج الرئيسي =====================
def main():
    cmd("I")
    cmd("W")
    calibrate()
    if USE_CAMERA:
        threading.Thread(target=camera_loop, daemon=True).start()
    print("جاهز! تكلم مع الوجه... (Ctrl+C للخروج)")

    try:
        while not stop_event.is_set():
            audio = listen_once()
            if audio is None or len(audio) < RATE * 0.5:
                cmd("I")
                continue

            cmd("T")
            try:
                heard, emotion, reply = ask_gemini(to_wav(audio))
            except Exception as e:
                print("خطأ Gemini:", str(e)[:200])
                cmd("s")
                time.sleep(2.5)
                cmd("I")
                cmd("n")
                continue

            print(f"انت: {heard}\nالوجه ({emotion}): {reply}\n")
            if not reply:
                cmd("I")
                continue

            cmd(EMOTION_CHAR.get(emotion, "n"))
            speak(reply)
            touch()
            time.sleep(0.4)   # لا يلتقط الميكروفون ذيل الصوت
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        cmd("I")
        cmd("n")
        arduino.close()
        print("تم الايقاف.")


if __name__ == "__main__":
    main()
