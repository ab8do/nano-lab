# Validation

## Current status

See the table in the main README (section 7). In short: sketches are compiled in CI; Dino and the Robo v3 + Gemini combination have been run on hardware by the author; everything else is unverified on hardware; **no quantitative measurements exist yet**.

## Proposed measurement protocol

Record these on a defined setup (board, display controller, laptop model, camera, lighting, OS, Python version) and report mean, standard deviation and sample size.

| Metric | How to measure | Notes |
|---|---|---|
| Gesture-to-pixel latency (Dino) | film the screen and the hand with a 120 fps phone camera; count frames between the hand crossing the threshold and the first sprite movement | ≥ 30 trials |
| Gesture accuracy | participant performs a scripted sequence (N raised hands, N fists, finger counts 1–5); compare with the logged output of the Python script | confusion matrix for finger counts |
| False triggers | 5 minutes of non-gesture movement in front of the camera; count spurious `J` | per lighting condition |
| Frame rate (Arduino) | toggle a spare pin each frame and measure with a logic analyser or oscilloscope | expected ≈ 33 fps (30 ms period) |
| Voice turn latency (Robo) | end of speech → first audio sample; timestamps printed by the host | per back-end |
| Recognition quality | word error rate on 50 prompts per language (MSA, Darija, French, English) | Whisper and Gemini |
| Token usage | the live meter printed by `voice_face_gemini_lite.py`; compare with `voice_face_ai.py` on the same prompts | tokens per turn |
| Memory | Arduino IDE output "Global variables use N bytes" after compiling | keep below ≈ 75 % for stack headroom |

## Manual test checklist

- [ ] Display shows the boot screen of each sketch (otherwise: wiring, soldering, SH1106 line).
- [ ] Dino: start screen waits; first raised hand starts the game; raising the hand again while airborne does nothing; after Game Over a raised hand restarts after about 1 s.
- [ ] Games: showing 1–4 fingers fills the highlighted row in 0.8 s and starts the game; `m` returns to the menu; Game Over retry (fist) and menu (five fingers) work.
- [ ] Robo: face blinks and glances; moving in front of the camera moves the eyes; speaking triggers listening bars, then thinking dots, then a talking mouth; 90 s of silence with nobody in view puts it to sleep; stepping in front of the camera wakes it.
- [ ] Token budget (Lite): meter prints per request; the battery icon updates.
