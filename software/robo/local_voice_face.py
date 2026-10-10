"""
وجه ذكي تفاعلي - نسخة مجانية بلا حدود (تعمل على جهازك)

  الاذن   : faster-whisper  (تعرف على الكلام محليا، عربي/فرنسي/انجليزي)
  العقل   : Ollama           (نموذج لغوي محلي، بلا مفتاح وبلا حدود)
  الصوت   : edge-tts         (مجاني بلا مفتاح، فيه صوت جزائري ar-DZ) + pyttsx3 احتياطي بلا انترنت
  الوجه   : smart_face_v3.ino على الاردوينو

التثبيت:
    1) ثبّت Ollama من https://ollama.com ثم في CMD:   ollama pull qwen3:4b
    2) pip install ollama faster-whisper sounddevice numpy opencv-python pyserial edge-tts miniaudio pyttsx3

التشغيل:
    غيّر PORT ثم:  python local_voice_face.py
"""

import asyncio
import itertools
import queue
import re
import threading
import time
from collections import deque

import numpy as np
import serial
import sounddevice as sd

import edge_tts
import miniaudio
import ollama
from faster_whisper import WhisperModel

# ===================== الاعدادات =====================
PORT = "COM3"          # منفذ الاردوينو
BAUD = 57600           # نفس Serial.begin(57600) في smart_face_v3.ino

# اول نموذج مثبت من هذه القائمة سيُستعمل (ثبّت واحدا بـ: ollama pull <الاسم>)
OLLAMA_MODELS = ["gemma4:e4b", "gemma4:e2b", "qwen3:4b", "gemma3:4b", "qwen2.5:3b", "llama3.2:3b"]

WHISPER_MODEL = "small"   # tiny / base / small / medium / large-v3-turbo  (الاكبر ادق لكن ابطأ)
WHISPER_DEVICE = "auto"   # auto = يستعمل كرت الشاشة ان وجد وإلا المعالج
ALLOWED_LANGS = ("ar", "fr", "en")

# اصوات edge-tts (لعرض كل الاصوات: edge-tts --list-voices)
VOICES = {
    "ar": "ar-DZ-AminaNeural",     # جزائري. بديل ذكوري: ar-DZ-IsmaelNeural
    "fr": "fr-FR-DeniseNeural",
    "en": "en-US-AriaNeural",
}

USE_CAMERA = True      # العينان تتبعان وجهك
SLEEP_AFTER = 90       # ثواني بلا صوت ولا وجه قبل ان ينعس
MIC_THRESHOLD = None   # None = معايرة تلقائية. او ضع رقما مثل 800
# ======================================================

SYSTEM_PROMPT = """You are 'Robo', a tiny cheerful, witty robot whose face lives on a small OLED screen.
You talk with the user by voice. The user may speak Arabic (including Algerian Darija), French or English.
Rules:
- Always answer in the same language the user spoke. For Arabic, use simple clear Arabic.
- Keep it short: one or two spoken sentences. No emojis, no markdown, no lists, no stage directions.
- Be warm, curious and playful, with a bit of personality.
- Start your answer with exactly one emotion tag in square brackets, chosen from:
  [neutral] [happy] [sad] [angry] [surprised] [love] [sleepy] [wink] [laugh]
  Example: [happy] Hello my friend, nice to see you!"""

EMO_CHAR = {"neutral": "n", "happy": "h", "sad": "s", "angry": "a", "surprised": "u",
            "love": "l", "sleepy": "z", "wink": "k", "laugh": "g",
            "excited": "h", "joy": "h", "funny": "g", "laughing": "g", "curious": "u",
            "thinking": "n", "shy": "l", "tired": "z"}

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


def cmd(c: str):
    send(bytes([254, ord(c)]))


def gaze(x, y):
    send(bytes([255, int(max(0, min(100, x))), int(max(0, min(100, y)))]))


def mouth(level):
    send(bytes([253, int(max(0, min(100, level)))]))


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
        print("معايرة ضجيج الغرفة (ثانية، لا تتكلم)...")
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK) as s:
            vals = [rms(s.read(BLOCK)[0][:, 0]) for _ in range(33)]
        THRESH = max(float(np.percentile(vals, 90)) * 3.0, 450.0)
    print(f"عتبة الصوت: {THRESH:.0f}")


def listen_once():
    pre = deque(maxlen=10)
    frames = []
    speaking = False
    speech_blocks = silence_blocks = 0
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
                if len(frames) % 3 == 0:
                    mouth(min(100, level / (THRESH * 5) * 100))   # موجات الاستماع تتفاعل مع صوتك
                silence_blocks = 0 if level > THRESH * 0.6 else silence_blocks + 1
                if silence_blocks > 33 or len(frames) > 500:
                    break
    return np.concatenate(frames) if frames else None


# ===================== الاذن: faster-whisper =====================
print("تحميل نموذج التعرف على الصوت (اول مرة يحتاج انترنت للتحميل)...")
whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type="int8")

JUNK = {"thank you", "thanks for watching", "merci", "merci d'avoir regardé",
        "اشتركوا في القناة", "شكرا للمشاهدة", "شكراً للمشاهدة", "you"}


def transcribe(audio):
    x = audio.astype(np.float32) / 32768.0

    def run(lang):
        segs, info = whisper.transcribe(x, beam_size=1, language=lang, vad_filter=True,
                                        condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segs).strip(), info.language

    text, lang = run(None)
    if lang not in ALLOWED_LANGS:          # كثيرا ما تُفهم العربية فارسية/اردية، نعيد المحاولة بالعربية
        text, lang = run("ar")
    if text.lower().strip(" .!؟?") in JUNK:
        return "", lang
    return text, lang


# ===================== العقل: Ollama =====================
def pick_model():
    try:
        names = [m["model"] for m in ollama.list()["models"]]
    except Exception as e:
        print("تعذر الاتصال بـ Ollama. ثبّته من ollama.com وتأكد انه يعمل.", e)
        raise SystemExit
    for pref in OLLAMA_MODELS:
        for n in names:
            if n == pref or n.startswith(pref):
                return n
    if names:
        print(f"لم اجد نموذجا من القائمة، سأستعمل: {names[0]}")
        return names[0]
    print("لا يوجد اي نموذج. نفّذ في CMD:  ollama pull qwen3:4b")
    raise SystemExit


MODEL = pick_model()
print("النموذج المحلي:", MODEL)
history = deque(maxlen=8)


def open_stream(messages):
    """يفتح بثا للرد (يجرب تعطيل وضع التفكير ان كان مدعوما)."""
    base = dict(model=MODEL, messages=messages, stream=True, keep_alive="30m",
                options={"temperature": 0.8, "num_predict": 150})
    last = None
    for think in (False, None):
        try:
            kw = dict(base)
            if think is not None:
                kw["think"] = think
            gen = ollama.chat(**kw)
            first = next(gen)     # يرسل الطلب فعليا
            return itertools.chain([first], gen)
        except Exception as e:
            last = e
    raise last


# ===================== الصوت: edge-tts =====================
def edge_synth(text, voice):
    async def go():
        data = b""
        async for ch in edge_tts.Communicate(text, voice).stream():
            if ch["type"] == "audio":
                data += ch["data"]
        return data

    mp3 = asyncio.run(go())
    dec = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16,
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


class Speaker:
    """يحوّل الجمل الى صوت اثناء توليد النموذج للجملة التالية (يقلل الانتظار)."""

    def __init__(self, stt_lang):
        self.stt_lang = stt_lang if stt_lang in VOICES else "en"
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

    def _lang_of(self, text):
        return "ar" if re.search(r"[\u0600-\u06FF]", text) else (
            self.stt_lang if self.stt_lang != "ar" else "en")

    def _synth(self):
        while True:
            text = self.tq.get()
            if text is None:
                self.aq.put(None)
                return
            try:
                audio, rate = edge_synth(text, VOICES[self._lang_of(text)])
                self.aq.put(("pcm", audio, rate))
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


ENDS = ".!?؟…\n"


def find_boundary(s):
    for i in range(len(s) - 1):
        if s[i] in ENDS and s[i + 1].isspace():
            return i
    if len(s) > 90:
        for i in range(len(s) - 2, 40, -1):
            if s[i] in ",،;؛":
                return i
    return None


def respond(user_text, stt_lang):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history) + \
           [{"role": "user", "content": user_text}]
    spk = Speaker(stt_lang)
    buf, full = "", ""
    emo_done = False
    try:
        for part in open_stream(msgs):
            buf += part["message"]["content"]

            # تجاهل كتل التفكير ان ظهرت
            if "<think>" in buf and "</think>" not in buf:
                continue
            if "</think>" in buf:
                buf = buf.split("</think>", 1)[1]

            if not emo_done:
                s = buf.lstrip()
                if not s:
                    continue
                if s.startswith("["):
                    end = s.find("]")
                    if end == -1 and len(s) < 20:
                        continue
                    if end != -1:
                        tag = s[1:end].strip().lower()
                        cmd(EMO_CHAR.get(tag, "n"))      # الوجه يتفاعل قبل ان يبدأ الصوت
                        buf = s[end + 1:]
                emo_done = True

            while True:
                cut = find_boundary(buf)
                if cut is None:
                    break
                sent, buf = buf[:cut + 1], buf[cut + 1:].lstrip()
                full += sent + " "
                spk.say(sent)

        if buf.strip():
            full += buf
            spk.say(buf)
    finally:
        spk.finish()

    full = clean(full)
    print(f"الوجه: {full}\n")
    if full:
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": full})


# ===================== البرنامج الرئيسي =====================
def main():
    cmd("I")
    cmd("W")
    calibrate()
    try:   # تحميل النموذج في الذاكرة مسبقا لتسريع اول رد
        ollama.chat(model=MODEL, messages=[{"role": "user", "content": "hi"}],
                    options={"num_predict": 1}, keep_alive="30m")
    except Exception:
        pass
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
                text, lang = transcribe(audio)
            except Exception as e:
                print("خطأ التعرف على الصوت:", str(e)[:150])
                cmd("s"); time.sleep(2); cmd("I"); cmd("n")
                continue
            if len(text) < 2:
                cmd("I")
                continue

            print(f"انت ({lang}): {text}")
            try:
                respond(text, lang)
            except Exception as e:
                print("خطأ النموذج المحلي (هل Ollama يعمل؟):", str(e)[:150])
                cmd("s"); time.sleep(2.5); cmd("I"); cmd("n")
                continue
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
