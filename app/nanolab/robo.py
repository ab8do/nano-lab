"""Robo engine: microphone -> Gemini (audio in, text out) -> edge-tts voice, driving the face.

Token-saving design (same as software/robo/voice_face_gemini_lite.py): one request per turn,
minimal thinking, short plain-text answers, silence trimming, noise gating, short memory,
token meter and budget. The voice comes from edge-tts, so speech never costs Gemini tokens.
"""
import asyncio
import io
import queue
import re
import threading
import time
import wave
from collections import deque

import numpy as np
import sounddevice as sd

import edge_tts
import miniaudio
from google import genai
from google.genai import types

from .camera import open_camera
from .engine import Engine
from .logbus import log
from .preview import PREVIEW

MODELS = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
MAX_OUT_TOKENS = 160
MAX_AUDIO_SECONDS = 12
SLEEP_AFTER = 90
VOICES = {"ar": "ar-DZ-AminaNeural", "fr": "fr-FR-DeniseNeural", "en": "en-US-AriaNeural"}
EMO_CHAR = {"neutral": "n", "happy": "h", "sad": "s", "angry": "a", "surprised": "u",
            "love": "l", "sleepy": "z", "wink": "k", "laugh": "g"}
AR = r"[\u0600-\u06FF]"
RATE, BLOCK = 16000, 480

BASE_PROMPT = ("You are Robo, a cheerful little robot face talking by voice. "
               "Reply in the user's language (Arabic/Darija, French or English), max 2 short sentences, "
               "no emojis or markdown. Start with one tag: "
               "[neutral][happy][sad][angry][surprised][love][sleepy][wink][laugh]. "
               "The user message is an audio clip.")


def rms(x):
    return float(np.sqrt(np.mean(x.astype(np.float32) ** 2)))


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


def to_wav(audio):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


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


class RoboEngine(Engine):
    name = "Robo"
    baud = 57600

    # ------------------------------------------------------------------ setup
    def run(self):
        key = (self.cfg.get("api_key") or "").strip()
        if not key:
            raise RuntimeError("api_key")
        self.client = genai.Client(api_key=key)
        self.turns = int(self.cfg.get("history_turns", 3))
        self.budget = int(self.cfg.get("token_budget", 100000))
        self.system = BASE_PROMPT + (" After your reply add ||| and a very short transcript of what the user said."
                                     if self.turns > 0 else "")
        self.history = deque(maxlen=max(0, self.turns) * 2)
        self.model_idx = 0
        self.usage = {"in": 0, "out": 0, "calls": 0}
        self.state = {"last": time.time(), "asleep": False}
        self.cam_stop = threading.Event()
        self.spk = None
        self.thresh = 500.0

        self.link.cmd("I")
        self.link.cmd("W")
        self.link.energy(100)
        self.calibrate()
        if self.cfg.get("robo_camera", True):
            threading.Thread(target=self.camera_loop, daemon=True).start()
        log("Robo: ready, speak to the face")
        out_of_budget = False

        while not self.stop.is_set():
            self.info = {**self.info, "state": "listening"}
            audio = self.listen_once()
            if audio is None:
                self.link.cmd("I")
                continue
            self.link.cmd("T")
            self.info = {**self.info, "state": "thinking"}
            if self.total_tokens() >= self.budget:
                if not out_of_budget:
                    out_of_budget = True
                    log("Robo: token budget finished, going to sleep")
                    self.link.cmd("z")
                    self.state["asleep"] = True
                    self.speak("وصلتُ للحد المسموح به، سأرتاح قليلا.", "ar")
                self.link.cmd("I")
                continue
            try:
                emo, reply, heard = self.ask(audio)
            except Exception as e:
                log(f"Robo: Gemini error: {str(e)[:160]}")
                self.link.cmd("s")
                time.sleep(2.5)
                self.link.cmd("I")
                self.link.cmd("n")
                continue
            if heard:
                log(f"You: {heard}")
            if not reply:
                self.link.cmd("I")
                continue
            log(f"Robo: {reply}")
            self.info = {**self.info, "state": "speaking", "heard": heard, "reply": reply}
            self.link.cmd(emo)
            self.speak(reply, guess_lang(reply))
            self.touch()
            time.sleep(0.4)

    def cleanup(self):
        self.cam_stop.set()
        try:
            sd.stop()
        except Exception:
            pass
        try:
            self.link.cmd("I")
            self.link.cmd("n")
        except Exception:
            pass
        PREVIEW.clear()

    def touch(self):
        self.state["last"] = time.time()

    # ------------------------------------------------------------------ camera (gaze)
    def camera_loop(self):
        import cv2
        try:
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            cap = open_camera(self.cfg.get("camera", 0))
        except Exception as e:
            log(f"Robo: camera unavailable, eyes will not follow you ({e})")
            return
        last_seen = last_send = 0.0
        try:
            while not self.cam_stop.is_set() and not self.stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.1)
                    continue
                frame = cv2.flip(frame, 1)
                gray = cv2.cvtColor(cv2.resize(frame, (320, 240)), cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.2, 5, minSize=(40, 40))
                now = time.time()
                if len(faces):
                    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                    cx, cy = (x + w / 2) / 320.0, (y + h / 2) / 240.0
                    if now - last_send > 0.1:
                        self.link.gaze(cx * 100, cy * 100)          # frame already mirrored
                        last_send = now
                    if now - last_seen > 8:
                        self.link.cmd("W")
                        self.state["asleep"] = False
                    last_seen = now
                    self.touch()
                    s = frame.shape[1] / 320.0
                    cv2.rectangle(frame, (int(x * s), int(y * s)), (int((x + w) * s), int((y + h) * s)), (0, 255, 0), 2)
                PREVIEW.set_frame(frame)
                time.sleep(0.03)
        finally:
            cap.release()

    # ------------------------------------------------------------------ microphone
    def calibrate(self):
        manual = float(self.cfg.get("mic_threshold") or 0)
        if manual > 0:
            self.thresh = manual
        else:
            log("Robo: measuring room noise (1 s, stay quiet)...")
            with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK) as s:
                vals = [rms(s.read(BLOCK)[0][:, 0]) for _ in range(33)]
            self.thresh = max(float(np.percentile(vals, 90)) * 3.0, 450.0)
        log(f"Robo: sound threshold {self.thresh:.0f}")

    def listen_once(self):
        pre = deque(maxlen=10)
        frames = []
        speaking = False
        speech_blocks = silence_blocks = voiced = last_voice = 0
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=BLOCK) as stream:
            while not self.stop.is_set():
                data, _ = stream.read(BLOCK)
                chunk = data[:, 0].copy()
                level = rms(chunk)
                if not speaking:
                    pre.append(chunk)
                    speech_blocks = speech_blocks + 1 if level > self.thresh else 0
                    if speech_blocks >= 4:
                        speaking = True
                        frames = list(pre)
                        self.state["asleep"] = False
                        self.touch()
                        self.link.cmd("L")
                    elif (time.time() - self.state["last"] > SLEEP_AFTER) and not self.state["asleep"]:
                        self.link.cmd("z")
                        self.state["asleep"] = True
                else:
                    frames.append(chunk)
                    if level > self.thresh * 0.6:
                        voiced += 1
                        last_voice = len(frames)
                        silence_blocks = 0
                    else:
                        silence_blocks += 1
                    if len(frames) % 3 == 0:
                        self.link.mouth(min(100, level / (self.thresh * 5) * 100))
                    if silence_blocks > 33 or len(frames) > MAX_AUDIO_SECONDS * 33:
                        break
        if self.stop.is_set() or not frames or voiced < 12:
            return None
        return np.concatenate(frames[:last_voice + 8])

    # ------------------------------------------------------------------ Gemini
    def total_tokens(self):
        return self.usage["in"] + self.usage["out"]

    def record_usage(self, resp):
        u = getattr(resp, "usage_metadata", None)
        pin = (getattr(u, "prompt_token_count", 0) or 0) if u else 0
        pout = ((getattr(u, "candidates_token_count", 0) or 0) +
                (getattr(u, "thoughts_token_count", 0) or 0)) if u else 0
        self.usage["in"] += pin
        self.usage["out"] += pout
        self.usage["calls"] += 1
        left = max(0, 100 - self.total_tokens() * 100 // max(1, self.budget))
        self.link.energy(left)
        self.info = {**self.info, "tokens": self.total_tokens(), "budget": self.budget, "calls": self.usage["calls"]}
        log(f"Tokens: +{pin} in / +{pout} out, total {self.total_tokens()} of {self.budget}")

    def make_config(self, model, variant):
        kw = dict(system_instruction=self.system, max_output_tokens=MAX_OUT_TOKENS, temperature=0.8)
        if variant is not None:
            if model.startswith("gemini-3"):
                kw["thinking_config"] = types.ThinkingConfig(thinking_level=variant)
            elif "2.5" in model:
                kw["thinking_config"] = types.ThinkingConfig(thinking_budget=variant)
        return types.GenerateContentConfig(**kw)

    def generate(self, contents):
        last = None
        for i in range(len(MODELS)):
            idx = (self.model_idx + i) % len(MODELS)
            m = MODELS[idx]
            variants = ["MINIMAL", "LOW", None] if m.startswith("gemini-3") else ([0, None] if "2.5" in m else [None])
            for v in variants:
                try:
                    resp = self.client.models.generate_content(model=m, contents=contents, config=self.make_config(m, v))
                    self.model_idx = idx
                    return resp
                except Exception as e:
                    last = e
                    if "thinking" in str(e).lower() and v is not None:
                        continue
                    log(f"Robo: [{m}] failed: {str(e)[:110]}")
                    break
        raise last

    @staticmethod
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

    def ask(self, audio):
        contents = [types.Content(role=r, parts=[types.Part(text=t)]) for r, t in self.history]
        contents.append(types.Content(role="user", parts=[types.Part.from_bytes(data=to_wav(audio), mime_type="audio/wav")]))
        resp = self.generate(contents)
        self.record_usage(resp)
        emo, reply, heard = self.parse(resp.text)
        if reply and self.turns > 0:
            self.history.append(("user", (heard or "(voice)")[:160]))
            self.history.append(("model", reply[:200]))
        return emo, reply, heard

    # ------------------------------------------------------------------ voice
    def speak(self, text, lang):
        q_text, q_audio = queue.Queue(), queue.Queue()
        default = lang if lang in VOICES else "en"
        spoke = {"v": False}

        def synth():
            while True:
                t = q_text.get()
                if t is None:
                    q_audio.put(None)
                    return
                lg = "ar" if re.search(AR, t) else default
                try:
                    q_audio.put(("pcm",) + edge_synth(t, VOICES[lg]))
                except Exception as e:
                    log(f"Robo: edge-tts failed (internet?): {str(e)[:90]}")
                    q_audio.put(("text", t))

        def play():
            while True:
                item = q_audio.get()
                if item is None:
                    break
                if self.stop.is_set():
                    continue
                if not spoke["v"]:
                    self.link.cmd("S")
                    spoke["v"] = True
                if item[0] == "pcm":
                    self.play_with_mouth(item[1], item[2])
                else:
                    self.offline_speak(item[1])
            if spoke["v"]:
                self.link.mouth(0)
            self.link.cmd("I")

        t1 = threading.Thread(target=synth, daemon=True)
        t2 = threading.Thread(target=play, daemon=True)
        t1.start()
        t2.start()
        for sent in re.split(r"(?<=[.!?؟…])\s+", text):
            sent = clean(sent)
            if re.search(r"\w", sent):
                q_text.put(sent)
        q_text.put(None)
        t2.join()

    def play_with_mouth(self, audio, rate):
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
            if self.stop.is_set():
                sd.stop()
                break
            self.link.mouth(100 * lv / ref)
            wait = t0 + (k + 1) * step - time.time()
            if wait > 0:
                time.sleep(wait)
        else:
            sd.wait()
        self.link.mouth(0)

    @staticmethod
    def offline_speak(text):
        try:
            import pyttsx3
            eng = pyttsx3.init()
            eng.say(text)
            eng.runAndWait()
        except Exception as e:
            log(f"Robo: no fallback voice: {e}")
