# Troubleshooting

**The screen stays black.** Unsoldered header pins are the usual cause. Solder them, check the seven wires against the wiring table, and try the SH1106 constructor. Two colours (yellow strip, blue area) are normal.

**`Error connecting to Serial`.** Wrong COM port, or another program holds it (close the Arduino Serial Monitor). Check that the baud rate matches the sketch: 9600 for Dino, 57600 for Gesture Games and Robo.

**The gesture is detected but nothing moves.** The sketch and the Python file must belong to the same project because the three protocols differ. For Dino the game may simply be over; the current sketch restarts on a raised hand.

**`SyntaxError` at a `//` comment.** Python comments start with `#`; `//` is C++.

**Upload fails.** Many Nano clones need Tools → Processor → *ATmega328P (Old Bootloader)*. Try another USB cable (some only charge).

**CI shows a red cross on the Arduino job.** Open the failed run and read the compiler message; open an issue with it. (The sketches were checked against mock headers only, not the real toolchain, before the first CI run.)

**Robo does not hear me / hears noise.** Set `MIC_THRESHOLD` by hand (e.g. 800 if it triggers too often, 300 if never). Check Windows' default input device and microphone permissions.

**Robo does not speak.** edge-tts and Gemini speech need Internet; check the default output device. The fallback voice (pyttsx3) may lack an Arabic voice on your system.

**Gemini quota or model errors.** Model names change; the scripts try several. Free tiers have daily limits: use `voice_face_gemini_lite.py` and watch its token meter, or switch to `local_voice_face.py`.

**Python cannot install a package (`wheel` errors).** Your Python may be too new for some binary wheels; use Python 3.12.
