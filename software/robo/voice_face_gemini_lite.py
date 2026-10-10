"""
وجه ذكي تفاعلي + Gemini  (نسخة موفّرة للتوكنز)

ما الذي يوفّر التوكنز هنا؟
  1) الصوت يُنطق عبر edge-tts المجاني (لا يستهلك توكنز Gemini نهائيا)
  2) طلب واحد فقط لكل جملة تقولها (بدل طلبين)
  3) التفكير الداخلي للنموذج مُقلَّل الى الحد الادنى (thinking minimal / budget 0)
  4) اجابات قصيرة بسقف MAX_OUT_TOKENS وبصيغة نصية بسيطة (بدون JSON)
  5) تعليمات النظام قصيرة، والذاكرة آخر HISTORY_TURNS دورات فقط وكل دورة مقصوصة
  6) الصوت المرسل يُقص من الصمت ولا يُرسل اذا كان ضجيجا او قصيرا (الصوت = 32 توكن/ثانية)
  7) STT_MODE="whisper": الفهم يتم على جهازك والنص فقط يُرسل، مع ردود محلية جاهزة وكاش
  8) عداد توكنز وميزانية: ينعس الوجه ويتوقف عن الاتصال عند نفاد الميزانية

التثبيت:
    pip install -U google-genai sounddevice numpy opencv-python pyserial edge-tts miniaudio pyttsx3
    (فقط اذا اخترت STT_MODE="whisper":  pip install faster-whisper)
"""

import asyncio
import os
import queue
import re
import threading
import time
import wave
import io
from collections import deque

import numpy as np
import serial
import sounddevice as sd

import edge_tts
import miniaudio
from google import genai
from google.genai import types

# ===================== الاعدادات =====================
API_KEY = os.environ.get("GEMINI_API_KEY", "PASTE_YOUR_KEY_HERE")
PORT = "COM3"        # منفذ الاردوينو
BAUD = 57600         # نفس Serial.begin(57600)

# الاوفر اولا. ان فشل نموذج (اسم/حصة) ينتقل للتالي. للذكاء الاعلى ضع "gemini-3.8-flash" اولا
MODELS = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash"]

STT_MODE = "gemini"      # "gemini" = ارسال الصوت لـ Gemini (سهل) | "whisper" = فهم محلي ثم نص فقط (اوفر)
WHISPER_MODEL = "small"  # يُستعمل فقط في وضع whisper

MAX_OUT_TOKENS = 160     # سقف طول الرد (يشمل التفكير)
HISTORY_TURNS = 3        # كم دورة تتذكر (0 = بلا ذاكرة = اوفر ما يمكن)
MAX_AUDIO_SECONDS = 12   # اقصى مدة تسجيل ترسل
TOKEN_BUDGET = 100000    # ميزانية التوكنز لكل تشغيل. عند نفادها ينعس الوجه

VOICES = {"ar": "ar-DZ-AminaNeural", "fr": "fr-FR-DeniseNeural", "en": "en-US-AriaNeural"}

USE_CAMERA = True        # العينان تتبعان وجهك
SLEEP_AFTER = 90         # ثواني بلا صوت ولا وجه قبل ان ينعس
MIC_THRESHOLD = None     # None = معايرة تلقائية، او رقم مثل 800
# ======================================================

SYSTEM = ("You are Robo, a cheerful little robot face talking by voice. "
          "Reply in the user's language (Arabic/Darija, French or English), max 2 short sentences, "
          "no emojis or markdown. Start with one tag: "
          "[neutral][happy][sad][angry][surprised][love][sleepy][wink][laugh].")
if STT_MODE == "gemini":
    SYSTEM += " The user message is an audio clip."
    if HISTORY_TURNS > 0:
        SYSTEM += " After your reply add ||| and a very short transcript of what the user said."

EMO_CHAR = {"neutral": "n", "happy": "h", "sad": "s", "angry": "a", "surprised": "u",
            "love": "l", "sleepy": "z", "wink": "k", "laugh": "g"}

if API_KEY == "PASTE_YOUR_KEY_HERE":
    print("ضع مفتاح Gemini في API_KEY اولا (او في متغير البيئة GEMINI_API_KEY)")
    raise SystemExit
client = genai.Client(api_key=API_KEY)

# ===================== الاردوينو =====================
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


def cmd(c):
    send(bytes([254, ord(c)]))


def gaze(x, y):
    send(bytes([255, int(max(0, min(100, x))), int(max(0, min(100, y)))]))


def mouth(level):
    send(bytes([253, int(max(0, min(100, level)))]))


def energy(pct):
    send(bytes([252, int(max(0, min(100, pct)))]))


stop_event = threading.Event()
state = {"last_activity": time.time(), "asleep": False}


def touch():
    state["last_activity"] = time.time()


# ===================== عداد التوكنز =====================
usage = {"in": 0, "out": 0, "calls": 0}


def total_tokens():
    return usage["in"] + usage["out"]


def record_usage(resp):
    u = getattr(resp, "usage_metadata", None)
    pin = (getattr(u, "prompt_token_count", 0) or 0) if u else 0
    pout = ((getattr(u, "candidates_token_count", 0) or 0) +
            (getattr(u, "thoughts_token_count", 0) or 0)) if u else 0
    usage["in"] += pin
    usage["out"] += pout
    usage["calls"] += 1
    left = max(0, 100 - total_tokens() * 100 // TOKEN_BUDGET)
    energy(left)
    print(f"[توكنز] هذا الطلب: دخل {pin} / خرج {pout} | المجموع {total_tokens()} من {TOKEN_BUDGET} "
          f"({usage['calls']} طلب)")


# ===================== الكاميرا =====================
def camera_loop():
    import cv2
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("تعذر فتح الكاميرا، سيعمل الوجه بدون تتبع.")
        return
    last_seen, last_send = 0.0, 0.0
    while not stop_event.is_set():
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.1)
            continue
        gray = cv2.cvtColor(cv2.resize(frame, (320, 240)), cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.2, 5, minSize=(40, 40))
        now = time.time()
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx, cy = (x + w / 2) / 320.0, (y + h / 2) / 240.0
            if now - last_send > 0.1:
                gaze((1 - cx) * 100, cy * 100)
                last_send = now
            if now - last_seen > 8:
                cmd("W")
                state["asleep"] = False
            last_seen = now
            touch()
        time.sleep(0.05)
    cap.release()


# ===================== الميكروفون (مع قص الصمت لتوفير توكنز الصوت) =====================
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
        print("معايرة ضجيج الغرفة (ثانية، لا تتكلم)...")
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK) as s:
            vals = [rms(s.read(BLOCK)[0][:, 0]) for _ in range(33)]
        THRESH = max(float(np.percentile(vals, 90)) * 3.0, 450.0)
    print(f"عتبة الصوت: {THRESH:.0f}")


def listen_once():
    """يعيد صوتك مقصوصا من الصمت، او None اذا كان ضجيجا/قصيرا (فلا يُرسل شيء)."""
    pre = deque(maxlen=10)
    frames = []
    speaking = False
    speech_blocks = silence_blocks = voiced = last_voice = 0
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
                    state["asleep"] = False
                    touch()
                    cmd("L")
                elif (time.time() - state["last_activity"] > SLEEP_AFTER) and not state["asleep"]:
                    cmd("z")
                    state["asleep"] = True
            else:
                frames.append(chunk)
                if level > THRESH * 0.6:
                    voiced += 1
                    last_voice = len(frames)
                    silence_blocks = 0
                else:
                    silence_blocks += 1
                if len(frames) % 3 == 0:
                    mouth(min(100, level / (THRESH * 5) * 100))
                if silence_blocks > 33 or len(frames) > MAX_AUDIO_SECONDS * 33:
                    break
    if not frames or voiced < 12:          # اقل من ~0.4 ثانية كلام فعلي = ضجيج
        return None
    return np.concatenate(frames[:last_voice + 8])     # قص الصمت الطويل في النهاية


def to_wav(audio):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


# ===================== فهم محلي (اختياري) =====================
whisper = None


def load_whisper():
    global whisper
    from faster_whisper import WhisperModel
    print("تحميل نموذج Whisper المحلي...")
    whisper = WhisperModel(WHISPER_MODEL, device="auto", compute_type="int8")


JUNK = {"thank you", "thanks for watching", "merci", "you", "اشتركوا في القناة", "شكرا للمشاهدة"}


def transcribe(audio):
    x = audio.astype(np.float32) / 32768.0

    def run(lang):
        segs, info = whisper.transcribe(x, beam_size=1, language=lang, vad_filter=True,
                                        condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip(), info.language

    text, lang = run(None)
    if lang not in ("ar", "fr", "en"):
        text, lang = run("ar")
    if text.lower().strip(" .!؟?") in JUNK:
        return "", lang
    return text, lang


# ===================== ردود محلية بلا توكنز =====================
AR = r"[\u0600-\u06FF]"
LOCAL_RULES = [
    (r"(سلام|مرحبا|اهلا|أهلا|hello|\bhi\b|hey|bonjour|salut)", 4, "happy",
     {"ar": "أهلا بك! كيف حالك اليوم؟", "fr": "Salut ! Comment vas-tu ?", "en": "Hi there! How are you?"}),
    (r"(شكرا|شكراً|merci|thank)", 5, "happy",
     {"ar": "العفو، بكل سرور!", "fr": "De rien !", "en": "You're welcome!"}),
    (r"(مع السلامة|بالسلامة|au revoir|\bbye\b|goodbye|à bientôt)", 4, "wink",
     {"ar": "إلى اللقاء، أراك قريبا!", "fr": "À bientôt !", "en": "See you soon!"}),
    (r"(احبك|أحبك|je t.?aime|i love you)", 6, "love",
     {"ar": "وأنا أحبك أيضا يا صديقي!", "fr": "Moi aussi je t'aime !", "en": "I love you too, friend!"}),
    (r"(كم الساعة|الساعة كم|what time|quelle heure)", 8, "neutral", "TIME"),
]


def local_answer(text, lang):
    t = text.lower()
    words = len(t.split())
    l = "ar" if re.search(AR, t) else (lang if lang in ("fr", "en") else "en")
    for pat, maxw, emo, rep in LOCAL_RULES:
        if words <= maxw and re.search(pat, t):
            if rep == "TIME":
                now = time.strftime("%H:%M")
                rep = {"ar": f"الساعة الآن {now}", "fr": f"Il est {now}", "en": f"It's {now}"}
            return EMO_CHAR[emo], rep[l], l
    return None


cache = {}


def cache_key(text):
    k = re.sub(r"[^\w\s]", "", text.lower()).strip()
    return k if len(k.split()) >= 3 else None


# ===================== Gemini (طلب واحد لكل دورة) =====================
history = deque(maxlen=HISTORY_TURNS * 2)
_model_idx = 0


def make_config(model, variant):
    kw = dict(system_instruction=SYSTEM, max_output_tokens=MAX_OUT_TOKENS, temperature=0.8)
    if variant is not None:
        if model.startswith("gemini-3"):
            kw["thinking_config"] = types.ThinkingConfig(thinking_level=variant)
        elif "2.5" in model:
            kw["thinking_config"] = types.ThinkingConfig(thinking_budget=variant)
    return types.GenerateContentConfig(**kw)


def generate(contents):
    """يجرب النماذج بالترتيب، ويخفّض التفكير الى الادنى لكل نموذج."""
    global _model_idx
    last = None
    for i in range(len(MODELS)):
        idx = (_model_idx + i) % len(MODELS)
        m = MODELS[idx]
        variants = ["MINIMAL", "LOW", None] if m.startswith("gemini-3") else \
                   ([0, None] if "2.5" in m else [None])
        for v in variants:
            try:
                resp = client.models.generate_content(model=m, contents=contents,
                                                      config=make_config(m, v))
                _model_idx = idx
                return resp
            except Exception as e:
                last = e
                if "thinking" in str(e).lower() and v is not None:
                    continue                    # هذا المستوى غير مدعوم، جرّب الذي بعده
                print(f"[{m}] فشل: {str(e)[:120]}")
                break
    raise last


def parse(text):
    text = (text or "").strip()
    emo = "n"
    m = re.match(r"\s*\[([A-Za-z]+)\]\s*", text)
    if m:
        emo = EMO_CHAR.get(m.group(1).lower(), "n")
        text = text[m.end():]
    heard = ""
    if "|||" in text:
        text, heard = text.split("|||", 1)
    return emo, text.strip(), heard.strip()


def ask(text=None, audio=None):
    contents = [types.Content(role=r, parts=[types.Part(text=t)]) for r, t in history]
    if audio is not None:
        part = types.Part.from_bytes(data=to_wav(audio), mime_type="audio/wav")
    else:
        part = types.Part(text=text)
    contents.append(types.Content(role="user", parts=[part]))

    resp = generate(contents)
    record_usage(resp)
    emo, reply, heard = parse(resp.text)
    if reply and HISTORY_TURNS > 0:
        history.append(("user", (text or heard or "(voice)")[:160]))
        history.append(("model", reply[:200]))
    return emo, reply, heard


# ===================== الصوت: edge-tts (مجاني، بلا توكنز) =====================
def edge_synth(text, voice):
    async def go():
        data = b""
        async for ch in edge_tts.Communicate(text, voice).stream():
            if ch["type"] == "audio":
                data += ch["data"]
        return data

    dec = miniaudio.decode(asyncio.run(go()), output_format=miniaudio.SampleFormat.SIGNED16,
                           nchannels=1, sample_rate=24000)
    return np.frombuffer(dec.samples, dtype=np.int16), 24000


def play_with_mouth(audio, rate):
    step = 0.05
    n = max(1, int(rate * step))
    levels = [float(np.sqrt(np.mean(audio[i:i + n].astype(np.float32) ** 2)))
              for i in range(0, len(audio), n) if len(audio[i:i + n])]
    if not levels:
        return
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


def offline_speak(text):
    try:
        import pyttsx3
        eng = pyttsx3.init()
        eng.say(text)
        eng.runAndWait()
    except Exception as e:
        print("لا يوجد صوت احتياطي:", e)


def clean(s):
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"[*_`#~>|]", "", s)
    s = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf]", "", s)
    return s.strip()


def guess_lang(text):
    if re.search(AR, text):
        return "ar"
    if re.search(r"[éèêàçùûôîï]|\b(le|la|les|je|tu|est|et|un|une|des|pas|vous|bonjour)\b", text.lower()):
        return "fr"
    return "en"


class Speaker:
    """يولّد صوت الجملة التالية بينما تُنطق الحالية (يقلل الانتظار)."""

    def __init__(self, default_lang):
        self.default_lang = default_lang
        self.tq, self.aq = queue.Queue(), queue.Queue()
        self.spoke = False
        self.t1 = threading.Thread(target=self._synth, daemon=True)
        self.t2 = threading.Thread(target=self._play, daemon=True)
        self.t1.start()
        self.t2.start()

    def say(self, text):
        text = clean(text)
        if re.search(r"\w", text):
            self.tq.put(text)

    def finish(self):
        self.tq.put(None)
        self.t2.join()

    def _synth(self):
        while True:
            text = self.tq.get()
            if text is None:
                self.aq.put(None)
                return
            lang = "ar" if re.search(AR, text) else self.default_lang
            try:
                self.aq.put(("pcm",) + edge_synth(text, VOICES[lang]))
            except Exception as e:
                print("edge-tts فشل (انترنت؟):", str(e)[:100])
                self.aq.put(("text", text))

    def _play(self):
        while True:
            item = self.aq.get()
            if item is None:
                break
            if not self.spoke:
                cmd("S")
                self.spoke = True
            if item[0] == "pcm":
                play_with_mouth(item[1], item[2])
            else:
                offline_speak(item[1])
        if self.spoke:
            mouth(0)
        cmd("I")


def speak(reply, lang):
    spk = Speaker(lang if lang in VOICES else "en")
    try:
        for sent in re.split(r"(?<=[.!?؟…])\s+", reply):
            spk.say(sent)
    finally:
        spk.finish()


# ===================== البرنامج الرئيسي =====================
def handle_turn(audio):
    """يعيد (emo, reply, lang) او None."""
    if STT_MODE == "whisper":
        text, lang = transcribe(audio)
        if len(text) < 2:
            return None
        print(f"انت ({lang}): {text}")
        hit = local_answer(text, lang)
        if hit:
            print("[رد محلي: 0 توكنز]")
            return hit
        key = cache_key(text)
        if key and key in cache:
            print("[من الكاش: 0 توكنز]")
            return cache[key]
        emo, reply, _ = ask(text=text)
        result = (emo, reply, lang)
        if key and reply:
            if len(cache) > 40:
                cache.pop(next(iter(cache)))
            cache[key] = result
        return result

    emo, reply, heard = ask(audio=audio)
    if heard:
        print(f"انت: {heard}")
    return emo, reply, guess_lang(reply)


def main():
    cmd("I")
    cmd("W")
    energy(100)
    if STT_MODE == "whisper":
        load_whisper()
    calibrate()
    if USE_CAMERA:
        threading.Thread(target=camera_loop, daemon=True).start()
    print(f"جاهز! (وضع الفهم: {STT_MODE}) تكلم مع الوجه... (Ctrl+C للخروج)")
    out_of_budget = False

    try:
        while not stop_event.is_set():
            audio = listen_once()
            if audio is None:
                cmd("I")
                continue

            cmd("T")
            if total_tokens() >= TOKEN_BUDGET:
                if not out_of_budget:
                    out_of_budget = True
                    print("انتهت ميزانية التوكنز لهذا التشغيل. اعد التشغيل او ارفع TOKEN_BUDGET.")
                    cmd("z")
                    state["asleep"] = True
                    speak("وصلتُ للحد المسموح به، سأرتاح قليلا.", "ar")
                cmd("I")
                continue

            try:
                result = handle_turn(audio)
            except Exception as e:
                print("خطأ:", str(e)[:200])
                cmd("s"); time.sleep(2.5); cmd("I"); cmd("n")
                continue
            if not result or not result[1]:
                cmd("I")
                continue

            emo, reply, lang = result
            print(f"الوجه: {reply}\n")
            cmd(emo)
            speak(reply, lang)
            touch()
            time.sleep(0.4)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        cmd("I")
        cmd("n")
        arduino.close()
        print(f"تم الايقاف. مجموع التوكنز المستهلك: {total_tokens()} في {usage['calls']} طلب.")


if __name__ == "__main__":
    main()
