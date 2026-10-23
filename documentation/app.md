# Desktop app (Nano Lab)

One program for all three projects. It starts a small local web server and opens the control panel in your browser: pick the Arduino port, pick a project, press **Start**. When the project changes, the app uploads the matching firmware to the Nano by itself.

## For users

1. Download `NanoLab-windows.zip` (or `NanoLab-linux.tar.gz`) from the **Releases** page (or from the *Actions* tab → *Build desktop app* → artifacts).
2. Unzip and run `NanoLab` (`NanoLab.exe` on Windows). No Python and no libraries to install.
3. Plug in the Arduino Nano, choose its port, choose a project, press **Start**.
   - First time with a project: the firmware upload takes about 10–20 s.
   - Robo needs a Gemini API key (free from Google AI Studio). Untick *Remember the key* if the computer is shared.

Notes:
- Windows: the program is not code-signed, so SmartScreen shows *More info → Run anyway*; some antivirus programs distrust PyInstaller builds.
- Some Nano clones need the CH340 USB driver on Windows.
- Linux: add yourself to the serial group once (`sudo usermod -aG dialout $USER`, then log in again).
- The local Ollama + Whisper brain is not part of the app (it is large and needs separate installs); use `software/robo/local_voice_face.py` for it.

## For developers

```bash
pip install -r app/requirements.txt
python app/launcher.py                            # opens the control panel
python app/launcher.py --no-browser --port 8765   # fixed port, prints the URL with the session token
```

Layout:

```text
app/
├── launcher.py            entry point
├── nanolab/
│   ├── server.py          local HTTP server: page, JSON API, MJPEG camera stream
│   ├── engine.py          base class: one project = one thread talking to the Arduino
│   ├── dino.py games.py robo.py     the three projects
│   ├── handtrack.py       MediaPipe HandLandmarker (Tasks API), finger counting
│   ├── flasher.py         avrdude wrapper (tries 115200 then 57600 baud)
│   └── link.py preview.py config.py logbus.py camera.py util.py
└── web/index.html         control panel (EN / FR / AR, RTL)
```

Build inputs that CI generates and bundles: `app/firmware/{dino,games,robo}.hex` (compiled with `arduino-cli` for `arduino:avr:nano`), `app/tools/avrdude` (taken from the Arduino AVR tools package) and `app/assets/hand_landmarker.task`.

## Security notes

- The server listens on `127.0.0.1` only, requires a random per-session token (query string for the first page, `X-Token` header afterwards) and rejects requests whose `Host` header is not `127.0.0.1`/`localhost` with the right port. This blocks other websites from controlling the app (CSRF) and DNS-rebinding attempts.
- The Gemini key is kept in memory; it is written to `~/.nanolab/config.json` (plain text) only if *Remember the key* is ticked. Settings and the log (`app.log`) live in `~/.nanolab/`.
- The camera stream never leaves the computer; with Robo, recorded speech is sent to Google's Gemini API, and the text to be spoken is sent to Microsoft's edge-tts service.

## Validation status

The server API, the security checks and the Dino/Games engines were exercised with stubbed camera, serial port and MediaPipe; the control panel was checked in headless Chromium (English and Arabic). Not yet verified: the PyInstaller builds, the firmware upload on a real board, and the Robo engine end to end. See [validation.md](validation.md).
