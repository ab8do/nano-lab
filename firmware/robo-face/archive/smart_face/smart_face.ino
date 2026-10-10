// ===== Smart Face: وجه ذكي تفاعلي على OLED =====
// Arduino Nano + OLED 7-pin SPI + U8g2 (نمط Page Buffer لتوفير الذاكرة)
// التوصيل: CLK=D13, MOSI=D11, DC=D9, CS=D10, RES=D8
//
// البروتوكول (Serial 57600) من البايثون:
//   [255][x 0-100][y 0-100]  = اتجاه النظر (مكان وجه المستخدم في الكاميرا)
//   [254][حرف]               = امر:
//        حالات : I خامل | L يستمع | T يفكر | S يتكلم
//        مشاعر : n محايد | h سعيد | s حزين | a غاضب | u متفاجئ | l حب | z نعسان | k غمزة
//        W = استيقاظ/ترحيب
//   [253][مستوى 0-100]       = شدة الصوت لمزامنة الفم مع الكلام

#include <Arduino.h>
#include <U8g2lib.h>
#include <SPI.h>
#include <math.h>

// ---- اختر السطر الذي اشتغل معك (واحد فقط) ----
U8G2_SSD1306_128X64_NONAME_1_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 8);
//U8G2_SH1106_128X64_NONAME_1_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 8);

// ---- الحالات والمشاعر ----
#define ST_IDLE   0
#define ST_LISTEN 1
#define ST_THINK  2
#define ST_SPEAK  3

#define E_NEUTRAL   0
#define E_HAPPY     1
#define E_SAD       2
#define E_ANGRY     3
#define E_SURPRISED 4
#define E_LOVE      5
#define E_SLEEPY    6
#define E_WINK      7

// ---- هندسة الوجه (الشريط الاصفر العلوي 16 بكسل، والباقي ازرق) ----
const int EYE_W = 28, EYE_H = 26, EYE_CY = 24;
const int EYE_LX = 34, EYE_RX = 94;
const unsigned long FRAME_MS = 33;
const unsigned long EMO_HOLD = 7000;   // بعد كم ملي ثانية يعود الوجه للمحايد

uint8_t state = ST_IDLE, emo = E_NEUTRAL;
unsigned long emoTime = 0, lastFrame = 0, lastGaze = 0, lastMouthMsg = 0;
unsigned long nextSaccade = 0, nextBlink = 2500;
uint8_t gazeX = 50, gazeY = 50, mouthLevel = 0;
float lookX = 0, lookY = 0, tgtX = 0, tgtY = 0;
float openCur = 0, mouthOpen = 0, animT = 0;
int eyeH = 0;
int8_t blinkF = -1;
uint8_t heartR = 5, zStage = 0, dotsN = 0;

// ================= ادوات الرسم (مع قص الحواف) =================
void box(int x, int y, int w, int h) {
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > 128) w = 128 - x;
  if (y + h > 64) h = 64 - y;
  if (w <= 0 || h <= 0) return;
  u8g2.drawBox(x, y, w, h);
}

void rbox(int x, int y, int w, int h, int r) {
  if (w <= 0 || h <= 0) return;
  int rm = min((h - 2) / 2, (w - 2) / 2);
  if (r > rm) r = rm;
  if (r < 1 || x < 0 || y < 0 || x + w > 128 || y + h > 64) { box(x, y, w, h); return; }
  u8g2.drawRBox(x, y, w, h, r);
}

// منحنى: curv>0 ابتسامة، curv<0 عبوس (او قوس ∩)
void curve(int cx, int cy, int hw, int curv, int th) {
  for (int dx = -hw; dx <= hw; dx++) {
    int y = cy + (int)((long)curv * (hw * hw - dx * dx) / (hw * hw));
    box(cx + dx, y, 1, th);
  }
}

void heart(int cx, int cy, int r) {
  u8g2.drawDisc(cx - r, cy - r / 2, r);
  u8g2.drawDisc(cx + r, cy - r / 2, r);
  u8g2.drawTriangle(cx - 2 * r + 1, cy - r / 2 + 2, cx + 2 * r - 1, cy - r / 2 + 2, cx, cy + 2 * r);
}

// ================= الاستقبال من البايثون =================
uint8_t hdr = 0, got = 0, buf[2];

void handleCmd(uint8_t c) {
  unsigned long now = millis();
  switch (c) {
    case 'I': state = ST_IDLE; break;
    case 'L': state = ST_LISTEN; emo = E_NEUTRAL; emoTime = now; break;
    case 'T': state = ST_THINK; break;
    case 'S': state = ST_SPEAK; mouthOpen = 0; emoTime = now; break;
    case 'n': emo = E_NEUTRAL;   emoTime = now; break;
    case 'h': emo = E_HAPPY;     emoTime = now; break;
    case 's': emo = E_SAD;       emoTime = now; break;
    case 'a': emo = E_ANGRY;     emoTime = now; break;
    case 'u': emo = E_SURPRISED; emoTime = now; break;
    case 'l': emo = E_LOVE;      emoTime = now; break;
    case 'z': emo = E_SLEEPY;    emoTime = now; break;
    case 'k': emo = E_WINK;      emoTime = now; break;
    case 'W': emo = E_HAPPY; state = ST_IDLE; emoTime = now; nextBlink = now + 300; break;
  }
}

void readSerial() {
  while (Serial.available() > 0) {
    uint8_t b = Serial.read();
    if (b >= 253) { hdr = b; got = 0; continue; }
    if (hdr == 0) continue;
    buf[got++] = b;
    if (hdr == 255 && got == 2) { gazeX = buf[0]; gazeY = buf[1]; lastGaze = millis(); hdr = 0; }
    else if (hdr == 254 && got == 1) { handleCmd(buf[0]); hdr = 0; }
    else if (hdr == 253 && got == 1) { mouthLevel = buf[0]; lastMouthMsg = millis(); hdr = 0; }
  }
}

// ================= التحريك =================
void update() {
  unsigned long now = millis();
  animT = now / 1000.0;

  // --- النظر ---
  bool haveGaze = (now - lastGaze) < 2500;
  if (emo == E_SLEEPY) {
    tgtX = 0; tgtY = 3;
  } else if (state == ST_THINK) {
    tgtX = ((now / 900) % 2) ? 7 : -3;
    tgtY = -5;
  } else if (haveGaze) {
    tgtX = (gazeX - 50) * 8.0 / 50.0;
    tgtY = (gazeY - 50) * 5.0 / 50.0;
  } else if (state == ST_LISTEN) {
    tgtX = 0; tgtY = 0;
  } else if (now > nextSaccade) {
    tgtX = random(-8, 9);
    tgtY = random(-4, 5);
    nextSaccade = now + random(1200, 3800);
  }
  lookX += (tgtX - lookX) * 0.35;
  lookY += (tgtY - lookY) * 0.35;

  // --- الرمش ---
  float blinkFactor = 1.0;
  if (blinkF < 0 && now > nextBlink) {
    blinkF = 0;
    nextBlink = now + random(2200, 6000);
    if (random(5) == 0) nextBlink = now + 380;   // رمشة مزدوجة
  }
  if (blinkF >= 0) {
    blinkF++;
    blinkFactor = fabs(blinkF - 3) / 3.0;
    if (blinkF >= 6) { blinkF = -1; blinkFactor = 1.0; }
  }

  // --- فتحة العين ---
  float tOpen = 1.0;
  if (emo == E_SLEEPY) tOpen = 0.3 + 0.05 * sin(animT * 1.4);
  else if (state == ST_LISTEN) tOpen = 1.12;
  else if (emo == E_SURPRISED) tOpen = 1.2;
  openCur += (tOpen - openCur) * 0.25;
  eyeH = (int)(EYE_H * openCur * blinkFactor);
  if (eyeH < 0) eyeH = 0;

  // --- الفم عند الكلام ---
  if (state == ST_SPEAK) {
    float target;
    if (now - lastMouthMsg < 250) target = mouthLevel / 100.0;
    else target = (random(0, 101) / 100.0) * (((now / 200) % 2) ? 1.0 : 0.6);
    mouthOpen += (target - mouthOpen) * 0.6;
    emoTime = now;   // لا تنتهي العاطفة اثناء الكلام
  } else {
    mouthOpen += (0 - mouthOpen) * 0.5;
  }

  // --- عودة المشاعر للمحايد ---
  if (emo != E_NEUTRAL && emo != E_SLEEPY && (now - emoTime) > EMO_HOLD) emo = E_NEUTRAL;

  // --- قيم الزخارف ---
  heartR = 5 + ((now / 250) % 2);
  zStage = (now / 600) % 4;
  dotsN = (now / 350) % 4;
}

// ================= الرسم =================
void drawEye(uint8_t side) {
  int cx = (side == 0 ? EYE_LX : EYE_RX) + (int)lookX;
  int cy = EYE_CY + (int)lookY;

  if (emo == E_LOVE) { heart(cx, cy - 2, heartR); return; }
  if (emo == E_HAPPY || (emo == E_WINK && side == 1)) { curve(cx, cy + 5, 12, -9, 4); return; }

  int w = (emo == E_SURPRISED) ? 22 : EYE_W;
  int h = eyeH;
  if (h < 4) { box(cx - w / 2, cy - 1, w, 3); return; }
  rbox(cx - w / 2, cy - h / 2, w, h, 7);

  // الجفون (غضب / حزن)
  if ((emo == E_SAD || emo == E_ANGRY) && h > 10) {
    bool coverRight = (emo == E_SAD) ? (side == 1) : (side == 0);
    int x0 = cx - w / 2 - 1, x1 = cx + w / 2 + 1;
    int y0 = cy - h / 2 - 1, yd = cy - h / 2 + (h * 6) / 10;
    u8g2.setDrawColor(0);
    if (coverRight) u8g2.drawTriangle(x1, y0, x1, yd, x0, y0);
    else            u8g2.drawTriangle(x0, y0, x0, yd, x1, y0);
    u8g2.setDrawColor(1);
  }
}

void drawMouth() {
  const int cx = 64;
  if (state == ST_SPEAK) {
    int h = 3 + (int)(mouthOpen * 12);
    int w = 18 + (int)(mouthOpen * 8);
    if (emo == E_HAPPY || emo == E_LOVE) w += 6;
    rbox(cx - w / 2, 52 - h / 2, w, h, 4);
    return;
  }
  if (state == ST_THINK) { box(cx + 4, 52, 10, 2); return; }
  if (state == ST_LISTEN) { u8g2.drawCircle(cx, 52, 3); return; }

  switch (emo) {
    case E_NEUTRAL:   curve(cx, 51, 8, 2, 2); break;
    case E_HAPPY:
    case E_LOVE:
    case E_WINK:      curve(cx, 48, 14, 7, 2); break;
    case E_SAD:       curve(cx, 54, 9, -5, 2); break;
    case E_ANGRY:     curve(cx, 53, 10, -3, 2); break;
    case E_SURPRISED: u8g2.drawCircle(cx, 53, 5); u8g2.drawCircle(cx, 53, 4); break;
    case E_SLEEPY: {
      int r = 2 + (int)(1.5 + 1.5 * sin(animT * 1.5));
      u8g2.drawDisc(cx, 53, r);
      break;
    }
  }
}

void drawExtras() {
  if (state == ST_LISTEN) {   // موجات الميكروفون على الجانبين
    for (int i = 0; i < 3; i++) {
      int hgt = 3 + (int)(5 + 5 * sin(animT * 8 + i * 1.7));
      box(6 + i * 6, 58 - hgt, 3, hgt);
      box(119 - i * 6, 58 - hgt, 3, hgt);
    }
  }
  if (state == ST_THINK) {    // نقاط التفكير في الشريط الاصفر
    for (int i = 0; i < dotsN; i++) box(104 + i * 6, 5, 3, 3);
  }
  if (emo == E_SLEEPY) {      // z z Z
    u8g2.setFont(u8g2_font_6x10_tr);
    if (zStage > 0) u8g2.drawStr(98, 18, "z");
    if (zStage > 1) u8g2.drawStr(106, 14, "z");
    if (zStage > 2) u8g2.drawStr(114, 10, "Z");
  }
}

void drawFace() {
  u8g2.setDrawColor(1);
  drawEye(0);
  drawEye(1);
  drawMouth();
  drawExtras();
}

// ================= الاساسيات =================
void setup() {
  Serial.begin(57600);
  u8g2.begin();
  randomSeed(analogRead(A0));
  handleCmd('W');   // ترحيب عند التشغيل
}

void loop() {
  readSerial();
  if (millis() - lastFrame < FRAME_MS) return;
  lastFrame = millis();
  update();
  u8g2.firstPage();
  do {
    drawFace();
  } while (u8g2.nextPage());
}
