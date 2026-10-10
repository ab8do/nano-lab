# Serial protocols

All values are unsigned bytes. 8N1, no flow control.

## Dino (9600 baud)

| Byte | Meaning |
|---|---|
| `J` (0x4A) | jump; starts the game on the start screen; restarts after Game Over (ignored for 800 ms after dying) |
| `R` (0x52) | alias of `J` |

The host sends `J` once per raised-hand event (rising edge).

## Gesture Games (57600 baud)

Packet: `255, x, y, f`

| Field | Range | Meaning |
|---|---|---|
| x | 0–100 | palm centre, horizontal (mirrored image) |
| y | 0–100 | palm centre, vertical |
| f | 0–5 or 9 | extended fingers; 9 = no hand |

Command: `254, 'M'` returns to the menu.

Parser: any byte ≥ 254 starts a message; the following 3 (packet) or 1 (command) bytes are payload. Because payload bytes never exceed 100, the parser resynchronises immediately after a dropped byte. If no packet arrives for 500 ms the Nano treats the hand as absent.

Example: palm in the centre with a fist: `FF 32 32 00`.

## Robo face (57600 baud)

| Header | Payload | Meaning |
|---|---|---|
| 255 | x, y | gaze target, 0–100 each (face position in the webcam; 50,50 = straight ahead). Gaze is held for 2.5 s without updates. |
| 254 | c | command letter (below) |
| 253 | v | loudness 0–100: mouth opening while *speaking* (valid for 250 ms), user's loudness for the sound bars while *listening* (valid for 400 ms) |
| 252 | e | energy 0–100 (remaining token budget); battery icon for 4 s after each update, blinking below 25 %, heavy eyelids below 15 % (face v3 only) |

Commands:

| Letter | Meaning | Letter | Meaning |
|---|---|---|---|
| `I` | idle | `n` | neutral |
| `L` | listening (resets emotion to neutral) | `h` | happy |
| `T` | thinking | `s` | sad |
| `S` | speaking | `a` | angry |
| `W` | wake / greet | `u` | surprised |
| | | `l` | love |
| | | `z` | sleepy |
| | | `k` | wink |
| | | `g` | laugh |

Emotions expire back to neutral after 7 s (laugh 3.2 s, surprised 3 s, wink 2.5 s) unless the face is speaking; `sleepy` persists until another command.

Example: gaze slightly left and up, then happy: `FF 28 2D FE 68`.
