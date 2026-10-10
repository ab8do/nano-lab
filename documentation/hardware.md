# Hardware

## Bill of materials

| Qty | Part |
|---|---|
| 1 | Arduino Nano (ATmega328P) with header pins |
| 1 | OLED 0.96 inch, 128×64, 7-pin SPI, two colours (16 yellow rows above 48 blue rows) |
| 7 | Jumper wires, female–male |
| 1 | Breadboard |
| 1 | Soldering iron and solder |
| 1 | USB cable (data-capable) |
| 1 | Laptop with webcam and microphone (and speakers for Robo) |

## Wiring

| OLED pin | Nano pin | Role |
|---|---|---|
| GND | GND | ground |
| VCC | 5V | power |
| D0 (CLK) | D13 | SPI clock (hardware SCK) |
| D1 (MOSI) | D11 | SPI data (hardware MOSI) |
| RES | D8 | reset |
| DC | D9 | data / command |
| CS | D10 | chip select |

D13 and D11 are the Nano's hardware SPI pins, so the sketches use `HW_SPI` constructors. Disconnect USB before wiring.

## Soldering

Header pins that are only pushed into the breadboard do not make a reliable electrical connection: the holes of the Nano are slightly larger than the pins, leaving a gap. SPI needs thousands of clean transitions per second, so even a momentary loss of contact blanks the display.

1. Seat the pins in the breadboard, rest the Nano on them so that the pins protrude.
2. Heat pin and pad together for 2–3 s.
3. Touch the solder to the **joint** (not the iron); it should flow into a small cone.
4. Remove the solder, then the iron, and let it cool for 3 s without moving.

## Display variants

- Controller **SSD1306** or **SH1106**. In each sketch, comment one constructor line and enable the other. If the picture is shifted by two pixels or garbled, you are using the wrong one.
- The yellow/blue split is a property of the panel; the thin line between the colours is physical.

## Power

The display draws little current; USB power from the laptop is sufficient. Use 5 V on `VCC` for the usual breakout boards that include a regulator; check your module's documentation before using 3.3 V.
