# Architecture

## Division of labour

| Layer | Runs on | Responsibilities |
|---|---|---|
| Perception | laptop (Python) | hand landmarks (MediaPipe), face detection (OpenCV Haar), voice-activity detection, speech recognition |
| Cognition | laptop or cloud | language model, emotion tag, speech synthesis |
| Transport | USB serial | 9600 baud (Dino), 57600 baud (Games, Robo) |
| State and rendering | Arduino Nano | game logic or face animation, drawing to the OLED over SPI |

The Nano never receives images or audio, only a few bytes per frame.

## Arduino main loop (all sketches)

```text
loop():
    readSerial()                  # drain the UART buffer, parse headers/payload
    if millis() - lastFrame < FRAME_MS: return
    lastFrame = millis()
    update()                      # game rules / animation targets (may use random())
    draw()                        # pure function of state
```

- Frame period: 30 ms (Dino, Gesture Games), 33 ms (Robo face).
- Gesture Games and Robo draw in U8g2 page-buffer mode (`firstPage()/nextPage()`), which calls the drawing code once per page (8 pages). The drawing code must therefore be deterministic: everything that uses `random()` or `millis()` is evaluated in `update()` and stored in variables.
- A UART receive buffer of 64 bytes is enough: the host sends at most a few hundred bytes per second (Gesture Games: 4 bytes × ~30 Hz).

## Python host (Robo)

- Main thread: microphone loop (voice-activity detection), request to the AI engine, speech playback with mouth-level streaming.
- Camera thread (optional): face detection at about 15 Hz, gaze packets at 10 Hz, wake-up when a face reappears after 8 s.
- A lock serialises all serial writes from both threads.
- The Local back-end pipelines speech synthesis: a synthesis thread prepares the audio of sentence *n+1* while a playback thread plays sentence *n*, and replies are split into sentences as the model streams tokens.

## Robo face model

State: `idle`, `listening`, `thinking`, `speaking` (set by command letters `I L T S`).
Emotion: `neutral, happy, sad, angry, surprised, love, sleepy, wink, laugh` (`n h s a u l z k g`).

Each frame, target values for the expression parameters are chosen from the current emotion and state, and every parameter moves a fixed fraction (0.2–0.35) of the remaining distance to its target:

| Parameter | Effect |
|---|---|
| eye width, eye openness | surprise, listening (wider), sleepy (narrower) |
| cheek lift | 0 normal; up to 0.9 turns the eye into a smiling crescent (a black disc erases the lower part) |
| lid slant | angry (inner corners lower) and sad (outer corners lower) |
| lid drop | sleepy, tired (energy < 15 %) |
| brow height and tilt | emotion and thinking (one brow raised) |
| mouth curvature and half-width | smile, frown, flat |
| mouth openness | driven by voice loudness (`253`) while speaking; sinusoidal for laughter |

Blink: 6-frame closing/opening cycle every 2.2–6 s, with an occasional double blink. Glance: new random target every 1.2–3.8 s unless a gaze packet arrived in the last 2.5 s.
