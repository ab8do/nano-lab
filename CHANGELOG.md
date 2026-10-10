# Changelog

All notable changes to this project. Dates are 2026.

## 1.0.0 — repository release (10 Oct)
- First public layout: firmware, software, documentation, trilingual website in `docs/` (GitHub Pages), CI.

## Website (10 Oct)
- Trilingual (EN/FR/AR, with RTL), 3D scene (Three.js) with live OLED simulations of all demos, wiring diagram, protocol tables, back-end comparison, setup and FAQ.

## Robo face v3 and token-saving back-end (9 Oct)
- `smart_face_v3`: protocol header `252` (energy), battery icon, heavy eyelids below 15 %.
- `voice_face_gemini_lite.py`: one request per turn, minimal thinking, 160-token cap, edge-tts voice, silence trimming, noise gating, optional local Whisper, canned answers and cache, token meter and budget.

## Local back-end and face v2 (9 Oct)
- `local_voice_face.py`: faster-whisper + Ollama + edge-tts, sentence-level pipelining, offline fallback voice.
- `smart_face_v2`: smooth expression morphing, eyebrows, crescent eyes, tears, blush, laughter, spontaneous idle behaviour; page-buffer rendering.

## Robo v1 with Gemini (8 Oct)
- `smart_face` (v1) and `voice_face_ai.py`: gaze from webcam, four states, eight emotions, mouth driven by voice loudness, Gemini audio understanding and speech.

## Gesture Games (8 Oct)
- Menu and four games (Flappy, Pong, Snake, Shooter); 4-byte stream at 57600 baud; finger counting by distance with majority vote.

## Dino (7–8 Oct)
- Initial version with the Adafruit SSD1306 library, then rewritten with U8g2 for the two-colour SPI panel.
- Fixed: after Game Over the sketch waited for an `R` command that the Python host never sent, so the dino looked frozen although gestures were detected. `J` now also restarts, after a short lockout.
- Replaced `//` comments in the Python file with `#` (SyntaxError).
