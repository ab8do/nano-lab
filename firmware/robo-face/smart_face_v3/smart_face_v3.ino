// ===== Smart Face v3: وجه ذكي متطور + مؤشر طاقة (رصيد التوكنز) =====
// Arduino Nano + OLED 7-pin SPI + U8g2 (Page Buffer لتوفير الذاكرة)
// التوصيل: CLK=D13, MOSI=D11, DC=D9, CS=D10, RES=D8
//
// ما الجديد في v2:
//  - تعابير تنتقل بسلاسة (morphing) بدل التبديل المفاجئ
//  - حواجب متحركة، خدود/ابتسامة العينين، دمعة، احمرار الخدود، ضحك
//  - العينان تحدقان بك، والفم يتزامن مع الصوت، وموجات الميكروفون تتفاعل مع صوتك
//  - سلوكيات عفوية: غمزة/ابتسامة/تفاجؤ عشوائي وهو خامل
//
// بروتوكول Serial 57600:
//   [255][x 0-100][y 0-100]  اتجاه النظر
//   [254][حرف]               امر:
//        حالات : I خامل | L يستمع | T يفكر | S يتكلم
//        مشاعر : n محايد | h سعيد | s حزين | a غاضب | u متفاجئ | l حب | z نعسان | k غمزة | g ضحك
//        W = ترحيب/استيقاظ
//   [253][مستوى 0-100]       شدة الصوت (فم المتكلم / موجات الاستماع)
//   [252][طاقة 0-100]        رصيد التوكنز المتبقي: بطارية صغيرة في الركن، ويتعب الوجه عند نفادها

#include <Arduino.h>
#include <U8g2lib.h>
#include <SPI.h>
#include <math.h>

// ---- اختر السطر الذي اشتغل معك (واحد فقط) ----
U8G2_SSD1306_128X64_NONAME_1_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 8);
//U8G2_SH1106_128X64_NONAME_1_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 8);

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
#define E_LAUGH     8

const int EYE_LX = 34, EYE_RX = 94, EYE_CY = 26, EYE_H0 = 26;
const unsigned long FRAME_MS = 33;

uint8_t state = ST_IDLE, emo = E_NEUTRAL;
unsigned long emoUntil = 0, lastFrame = 0, lastGaze = 0, lastMouthMsg = 0;
unsigned long nextSaccade = 0, nextBlink = 2500, nextFun = 22000;
uint8_t gazeX = 50, gazeY = 50, mouthLevel = 0;

float lookX = 0, lookY = 0, tgtX = 0, tgtY = 0;
float openCur = 0, mouthOpen = 0, animT = 0, micLvl = 0;
float ewC = 28, cheekC[2] = {0, 0}, slantC = 0, lidC = 0;
float browYC = 0, browTC = 0, mCurveC = 2, mHWC = 8, thinkBrow = 0;
int eyeH = 0, shakeX = 0, bobY = 0, tearY = 0;
int8_t blinkF = -1;
uint8_t heartR = 5, zStage = 0, dotsN = 0;
uint8_t energy = 100;            // الطاقة المتبقية %
unsigned long lastEnergyMsg = 0;
bool showBat = false;

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

// منحنى: curv>0 ابتسامة، curv<0 عبوس
void curve(int cx, int cy, int hw, int curv, int th) {
  if (hw < 1) hw = 1;
  for (int dx = -hw; dx <= hw; dx++) {
    int y = cy + (int)((long)curv * (hw * hw - dx * dx) / (hw * hw));
    box(cx + dx, y, 1, th);
  }
}

// خط سميك (2 بكسل) آمن عند الحواف
void thickLine(int x0, int y0, int x1, int y1) {
  int dx = x1 - x0;
  if (dx == 0) { box(x0, min(y0, y1), 2, abs(y1 - y0) + 2); return; }
  int step = dx > 0 ? 1 : -1;
  for (int x = x0; x != x1 + step; x += step) {
    int y = y0 + (int)((long)(y1 - y0) * (x - x0) / dx);
    box(x, y, 1, 2);
  }
}

void heart(int cx, int cy, int r) {
  u8g2.drawDisc(cx - r, cy - r / 2, r);
  u8g2.drawDisc(cx + r, cy - r / 2, r);
  u8g2.drawTriangle(cx - 2 * r + 1, cy - r / 2 + 2, cx + 2 * r - 1, cy - r / 2 + 2, cx, cy + 2 * r);
}

void ring(int cx, int cy, int r) {
  u8g2.drawDisc(cx, cy, r);
  u8g2.setDrawColor(0);
  u8g2.drawDisc(cx, cy, r - 2);
  u8g2.setDrawColor(1);
}

// ================= الاستقبال =================
unsigned long holdFor(uint8_t e) {
  switch (e) {
    case E_SURPRISED: return 3000;
    case E_LAUGH:     return 3200;
    case E_WINK:      return 2500;
    default:          return 7000;
  }
}

void setEmo(uint8_t e) { emo = e; emoUntil = millis() + holdFor(e); }

void handleCmd(uint8_t c) {
  switch (c) {
    case 'I': state = ST_IDLE; break;
    case 'L': state = ST_LISTEN; setEmo(E_NEUTRAL); break;
    case 'T': state = ST_THINK; break;
    case 'S': state = ST_SPEAK; mouthOpen = 0; break;
    case 'n': setEmo(E_NEUTRAL);   break;
    case 'h': setEmo(E_HAPPY);     break;
    case 's': setEmo(E_SAD);       break;
    case 'a': setEmo(E_ANGRY);     break;
    case 'u': setEmo(E_SURPRISED); break;
    case 'l': setEmo(E_LOVE);      break;
    case 'z': setEmo(E_SLEEPY);    break;
    case 'k': setEmo(E_WINK);      break;
    case 'g': setEmo(E_LAUGH);     break;
    case 'W': setEmo(E_HAPPY); emoUntil = millis() + 2500; state = ST_IDLE; nextBlink = millis() + 300; break;
  }
}

uint8_t hdr = 0, got = 0, buf[2];

void readSerial() {
  while (Serial.available() > 0) {
    uint8_t b = Serial.read();
    if (b >= 252) { hdr = b; got = 0; continue; }
    if (hdr == 0) continue;
    buf[got++] = b;
    if (hdr == 255 && got == 2) { gazeX = buf[0]; gazeY = buf[1]; lastGaze = millis(); hdr = 0; }
    else if (hdr == 254 && got == 1) { handleCmd(buf[0]); hdr = 0; }
    else if (hdr == 253 && got == 1) { mouthLevel = buf[0]; lastMouthMsg = millis(); hdr = 0; }
    else if (hdr == 252 && got == 1) { energy = buf[0]; lastEnergyMsg = millis(); hdr = 0; }
  }
}

// ================= التحريك =================
void update() {
  unsigned long now = millis();
  animT = now / 1000.0;

  // --- انتهاء المشاعر المؤقتة ---
  if (emo != E_NEUTRAL && emo != E_SLEEPY && (long)(now - emoUntil) > 0) {
    if (state == ST_SPEAK) emoUntil = now + 2000;
    else emo = E_NEUTRAL;
  }

  // --- سلوك عفوي وهو خامل ---
  if (state == ST_IDLE && emo == E_NEUTRAL && now > nextFun) {
    uint8_t r = random(3);
    setEmo(r == 0 ? E_WINK : (r == 1 ? E_HAPPY : E_SURPRISED));
    emoUntil = now + 1600;
    nextFun = now + random(20000, 45000);
  }

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
    if (random(5) == 0) nextBlink = now + 380;
  }
  if (blinkF >= 0) {
    blinkF++;
    blinkFactor = fabs(blinkF - 3) / 3.0;
    if (blinkF >= 6) { blinkF = -1; blinkFactor = 1.0; }
  }

  // --- اهداف التعبير ---
  float tEw = 28, tEh = 1.0, tChL = 0, tChR = 0, tSl = 0, tLid = 0;
  float tBY = 0, tBT = 0, tMC = 2, tMH = 8;
  switch (emo) {
    case E_HAPPY:     tChL = tChR = 0.62; tBY = -1; tMC = 7; tMH = 14; break;
    case E_SAD:       tEh = 0.95; tSl = -1; tBY = 1; tBT = -3; tMC = -5; tMH = 9; break;
    case E_ANGRY:     tEh = 0.85; tSl = 1; tLid = 0.08; tBY = 2; tBT = 4; tMC = -3; tMH = 10; break;
    case E_SURPRISED: tEh = 1.2; tEw = 22; tBY = -3; break;
    case E_LOVE:      tBY = -1; tMC = 7; tMH = 14; break;
    case E_SLEEPY:    tEh = 0.5 + 0.05 * sin(animT * 1.4); tLid = 0.35; tBY = 2; tMC = 0; tMH = 5; break;
    case E_WINK:      tChR = 0.9; tChL = 0.05; tMC = 7; tMH = 12; tBY = -1; break;
    case E_LAUGH:     tChL = tChR = 0.7; tBY = -2; tMC = 8; tMH = 15; break;
  }
  if (state == ST_LISTEN) { if (tEh < 1.12) tEh = 1.12; tBY = -3; }
  if (state == ST_THINK)  { tBY = -1; }
  if (energy < 15 && emo != E_SLEEPY && tLid < 0.2) tLid = 0.2;   // تعب: جفون ثقيلة

  ewC     += (tEw - ewC) * 0.25;
  openCur += (tEh - openCur) * 0.25;
  cheekC[0] += (tChL - cheekC[0]) * 0.2;
  cheekC[1] += (tChR - cheekC[1]) * 0.2;
  slantC  += (tSl - slantC) * 0.2;
  lidC    += (tLid - lidC) * 0.2;
  browYC  += (tBY - browYC) * 0.25;
  browTC  += (tBT - browTC) * 0.25;
  mCurveC += (tMC - mCurveC) * 0.25;
  mHWC    += (tMH - mHWC) * 0.25;
  thinkBrow += (((state == ST_THINK) ? 3.0 : 0.0) - thinkBrow) * 0.25;

  eyeH = (int)(EYE_H0 * openCur * blinkFactor);
  if (eyeH < 0) eyeH = 0;

  // --- الفم / الاهتزاز ---
  float tOpen = 0;
  if (state == ST_SPEAK) {
    if (now - lastMouthMsg < 250) tOpen = mouthLevel / 100.0;
    else tOpen = (random(0, 101) / 100.0) * (((now / 200) % 2) ? 1.0 : 0.6);
  } else if (emo == E_LAUGH) {
    tOpen = 0.55 + 0.45 * sin(animT * 16);
  }
  mouthOpen += (tOpen - mouthOpen) * 0.6;

  if (state == ST_SPEAK) bobY = (int)(mouthOpen * 2);
  else if (emo == E_LAUGH) bobY = (int)(sin(animT * 22) * 1.5);
  else bobY = 0;
  shakeX = (emo == E_ANGRY) ? (int)random(-1, 2) : 0;

  micLvl = ((now - lastMouthMsg) < 400) ? mouthLevel / 100.0 : 0;

  tearY = (int)fmod(animT * 9.0, 20.0);
  heartR = 5 + ((now / 250) % 2);
  zStage = (now / 600) % 4;
  dotsN = (now / 350) % 4;
  // البطارية: تظهر 4 ثوان بعد كل تحديث، وتومض دائما اذا كانت الطاقة قليلة
  showBat = (lastEnergyMsg != 0 && (now - lastEnergyMsg) < 4000) || (energy < 25 && ((now / 500) % 2));
}

// ================= الرسم =================
void drawBrow(uint8_t side, int cx) {
  int by = 6 + (int)browYC + (int)(lookY * 0.4) + bobY;
  if (side == 1) by -= (int)thinkBrow;     // حاجب واحد يرتفع عند التفكير
  int tilt = (int)browTC;
  int outerX = (side == 0) ? cx - 10 : cx + 10;
  int innerX = (side == 0) ? cx + 10 : cx - 10;
  thickLine(outerX, by - tilt / 2, innerX, by + (tilt - tilt / 2));
}

void drawEye(uint8_t side) {
  int cx = (side == 0 ? EYE_LX : EYE_RX) + (int)lookX + shakeX;
  int cy = EYE_CY + (int)lookY + bobY;
  drawBrow(side, cx);

  if (emo == E_LOVE) { heart(cx, cy - 2, heartR); return; }

  int w = (int)ewC, h = eyeH;
  if (h < 4) { box(cx - w / 2, cy - 1, w, 3); return; }
  rbox(cx - w / 2, cy - h / 2, w, h, 7);

  int x0 = cx - w / 2 - 1, x1 = cx + w / 2 + 1, y0 = cy - h / 2 - 1;

  // جفن مائل (غضب/حزن)
  if (fabs(slantC) > 0.05 && h > 10) {
    int yd = y0 + 1 + (int)(fabs(slantC) * h * 0.6);
    bool coverRight = (slantC > 0) ? (side == 0) : (side == 1);
    u8g2.setDrawColor(0);
    if (coverRight) u8g2.drawTriangle(x1, y0, x1, yd, x0, y0);
    else            u8g2.drawTriangle(x0, y0, x0, yd, x1, y0);
    u8g2.setDrawColor(1);
  }
  // جفن علوي نازل (نعاس/ضيق)
  if (lidC > 0.03) {
    u8g2.setDrawColor(0);
    box(x0, y0, w + 2, (int)(lidC * h) + 1);
    u8g2.setDrawColor(1);
  }
  // رفع الخد: يحوّل العين الى هلال ^_^
  float ch = cheekC[side];
  if (ch > 0.03) {
    int domeTop = cy + h / 2 - (int)(ch * h);
    u8g2.setDrawColor(0);
    u8g2.drawDisc(cx, domeTop + 18, 18);
    u8g2.setDrawColor(1);
  }
}

void drawMouth() {
  const int cx = 64;
  if (mouthOpen > 0.12) {
    int h = 3 + (int)(mouthOpen * 11);
    int w = 16 + (int)(mouthOpen * 8) + (mCurveC > 4 ? 6 : 0);
    rbox(cx - w / 2, 53 - h / 2, w, h, 4);
    return;
  }
  if (emo == E_SURPRISED) { ring(cx, 53, 6); return; }
  if (state == ST_LISTEN) { ring(cx, 53, 4); return; }
  if (emo == E_SLEEPY) {
    int r = 2 + (int)(1.5 + 1.5 * sin(animT * 1.5));
    u8g2.drawDisc(cx, 53, r);
    return;
  }
  if (state == ST_THINK) { box(cx + 3, 53, 10, 2); return; }
  curve(cx, 53 - (int)(mCurveC * 2 / 3), (int)mHWC, (int)mCurveC, 2);
}

void drawExtras() {
  // مؤشر الطاقة (الركن العلوي الايسر)
  if (showBat) {
    u8g2.drawFrame(0, 0, 16, 7);
    box(16, 2, 2, 3);
    box(2, 2, (energy * 12) / 100, 3);
  }
  // موجات الميكروفون تتفاعل مع صوتك
  if (state == ST_LISTEN) {
    for (int i = 0; i < 3; i++) {
      int hgt = 2 + (int)(micLvl * 10) + (int)(2 + 2 * sin(animT * 10 + i * 1.7));
      box(6 + i * 6, 58 - hgt, 3, hgt);
      box(119 - i * 6, 58 - hgt, 3, hgt);
    }
  }
  // نقاط التفكير
  if (state == ST_THINK) {
    for (int i = 0; i < dotsN; i++) box(104 + i * 6, 5, 3, 3);
  }
  // احمرار الخدود
  if (emo == E_LOVE || (cheekC[0] + cheekC[1]) > 0.6) {
    for (int i = 0; i < 3; i++) {
      int lx = 8 + i * 4, rx = 106 + i * 4;
      box(lx, 45, 1, 1); box(lx + 1, 44, 1, 1); box(lx + 2, 43, 1, 1);
      box(rx, 45, 1, 1); box(rx + 1, 44, 1, 1); box(rx + 2, 43, 1, 1);
    }
  }
  // دمعة
  if (emo == E_SAD) {
    int tx = EYE_LX - 8 + (int)lookX, ty = EYE_CY + 16 + tearY;
    u8g2.drawDisc(tx, ty, 2);
    box(tx, ty - 4, 1, 3);
  }
  // علامة تعجب
  if (emo == E_SURPRISED) {
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(118, 11, "!");
  }
  // z z Z
  if (emo == E_SLEEPY) {
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
  handleCmd('W');
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
