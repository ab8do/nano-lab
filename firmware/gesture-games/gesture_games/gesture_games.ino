// ===== Gesture Games: Arduino Nano + OLED 7-pin SPI + U8g2 =====
// 4 العاب: Flappy Bird / Pong / Snake / Shooter
// التحكم من كاميرا اللابتوب عبر gesture_controller.py
// التوصيل: CLK=D13, MOSI=D11, DC=D9, CS=D10, RES=D8
//
// بروتوكول السيريال (57600): الحزمة = [255][x 0-100][y 0-100][اصابع 0-5 او 9 = لا توجد يد]
// امر القائمة = [254]['M']

#include <Arduino.h>
#include <U8g2lib.h>
#include <SPI.h>

// نمط Page Buffer لتوفير الذاكرة (الذاكرة في النانو صغيرة 2KB)
// ---- اختر السطر الذي اشتغل معك (واحد فقط) ----
U8G2_SSD1306_128X64_NONAME_1_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 8);
//U8G2_SH1106_128X64_NONAME_1_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 8);

#define M_MENU   0
#define M_FLAPPY 1
#define M_PONG   2
#define M_SNAKE  3
#define M_SHOOT  4

const unsigned long FRAME_MS = 30;

void enterMode(uint8_t m);

// ================= الادخال من البايثون =================
uint8_t hx = 50, hy = 50, hf = 9;          // موضع اليد وعدد الاصابع
unsigned long lastPacket = 0, holdStart = 0;
bool goMenu = false;
uint8_t pkt[3];
uint8_t pidx = 0;
bool inPkt = false, inCmd = false;

bool handPresent() { return hf != 9 && (millis() - lastPacket) < 500; }

// هل بقي عدد الاصابع f ثابتا لمدة ms ؟
bool held(uint8_t f, unsigned long ms) {
  return handPresent() && hf == f && (millis() - holdStart) >= ms;
}

void readSerial() {
  while (Serial.available() > 0) {
    uint8_t b = Serial.read();
    if (b == 255) { inPkt = true; inCmd = false; pidx = 0; continue; }
    if (b == 254) { inCmd = true; inPkt = false; continue; }
    if (inCmd) { if (b == 'M') goMenu = true; inCmd = false; continue; }
    if (inPkt) {
      pkt[pidx++] = b;
      if (pidx >= 3) {
        if (pkt[2] != hf) holdStart = millis();
        hx = pkt[0]; hy = pkt[1]; hf = pkt[2];
        lastPacket = millis();
        inPkt = false;
      }
    }
  }
}

// ================= متغيرات عامة =================
uint8_t mode = M_MENU;
bool over = false;
unsigned long overTime = 0, lastFrame = 0;
int score = 0;
int lives = 3;
int best[4] = {0, 0, 0, 0};
unsigned int frameNo = 0;

// ================= ادوات الرسم (مع قص الحواف) =================
void px(int x, int y) {
  if (x < 0 || y < 0 || x > 127 || y > 63) return;
  u8g2.drawPixel(x, y);
}

void box(int x, int y, int w, int h) {
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > 128) w = 128 - x;
  if (y + h > 64) h = 64 - y;
  if (w <= 0 || h <= 0) return;
  u8g2.drawBox(x, y, w, h);
}

void centerText(const char* s, int y) {
  u8g2.drawStr((128 - u8g2.getStrWidth(s)) / 2, y, s);
}

int mapPos(int v, int lo, int hi) {
  return lo + (long)v * (hi - lo) / 100;
}

void header(const char* t, int sc) {
  u8g2.setFont(u8g2_font_5x7_tr);
  u8g2.setDrawColor(1);
  u8g2.drawStr(0, 9, t);
  char b[10];
  snprintf(b, sizeof(b), "%d", sc);
  u8g2.drawStr(128 - u8g2.getStrWidth(b) - 2, 9, b);
}

void die() {
  over = true;
  overTime = millis();
  holdStart = millis();
  if (score > best[mode - 1]) best[mode - 1] = score;
}

// ================= 1) Flappy Bird =================
// ايماءة الطيران: اقفل يدك ثم افتحها
const int BX = 28;
const int PIPE_W = 12, GAP_H = 22, FLOOR_Y = 62;
float fy, fvy;
bool fStarted, flapArmed;
float pipeX[2];
uint8_t pipeGap[2];
bool pipePassed[2];

void flappyInit() {
  fy = 36; fvy = 0; fStarted = false; flapArmed = false;
  for (uint8_t i = 0; i < 2; i++) {
    pipeX[i] = 140 + i * 66;
    pipeGap[i] = random(24, 37);
    pipePassed[i] = false;
  }
}

void flappyUpdate() {
  bool flap = false;
  if (handPresent()) {
    if (hf <= 2) flapArmed = true;
    else if (hf >= 4 && flapArmed) { flap = true; flapArmed = false; }
  }
  if (flap) { fStarted = true; fvy = -3.4; }
  if (!fStarted) return;

  fvy += 0.3;
  fy += fvy;
  if (fy < 16) { fy = 16; fvy = 0; }

  for (uint8_t i = 0; i < 2; i++) {
    pipeX[i] -= 2;
    if (pipeX[i] < -PIPE_W - 2) {
      pipeX[i] += 132;
      pipeGap[i] = random(24, 37);
      pipePassed[i] = false;
    }
    if (!pipePassed[i] && pipeX[i] + PIPE_W < BX) { pipePassed[i] = true; score++; }
    if (BX + 8 > pipeX[i] && BX < pipeX[i] + PIPE_W) {
      if (fy < pipeGap[i] || fy + 6 > pipeGap[i] + GAP_H) { die(); return; }
    }
  }
  if (fy + 6 >= FLOOR_Y) die();
}

void flappyDraw() {
  header("FLAPPY", score);
  u8g2.drawHLine(0, FLOOR_Y, 128);
  for (uint8_t i = 0; i < 2; i++) {
    int x = (int)pipeX[i];
    int g = pipeGap[i];
    box(x, 16, PIPE_W, g - 20);
    box(x - 1, g - 4, PIPE_W + 2, 4);
    box(x - 1, g + GAP_H, PIPE_W + 2, 4);
    box(x, g + GAP_H + 4, PIPE_W, FLOOR_Y - (g + GAP_H + 4));
  }
  int y = (int)fy;
  box(BX + 1, y, 6, 6);
  box(BX, y + 1, 8, 4);
  box(BX + 8, y + 3, 2, 2);
  u8g2.setDrawColor(0);
  px(BX + 5, y + 1);
  u8g2.setDrawColor(1);
  if (!fStarted) {
    u8g2.setFont(u8g2_font_5x7_tr);
    centerText("Close then open hand", 56);
  }
}

// ================= 2) Pong =================
// ايماءة: حرّك يدك لاعلى/اسفل لتحريك المضرب
const int PH = 14;
float bx, by, bvx, bvy, aiY;

int paddleY() { return mapPos(hy, 16, 62 - PH); }

void pongServe(int dir) {
  bx = 64; by = 40;
  bvx = 2.0 * dir;
  bvy = random(-12, 13) / 10.0;
}

void pongInit() {
  lives = 3; aiY = 30;
  pongServe(-1);
}

void pongUpdate() {
  bx += bvx; by += bvy;
  if (by < 17) { by = 17; bvy = -bvy; }
  if (by > 59) { by = 59; bvy = -bvy; }

  int py = paddleY();
  // مضرب اللاعب
  if (bvx < 0 && bx <= 7 && bx >= 2 && by + 3 > py && by < py + PH) {
    bvx = -bvx * 1.05;
    if (bvx > 4.5) bvx = 4.5;
    bvy = ((by + 1.5) - (py + PH / 2.0)) / (PH / 2.0) * 2.2;
    score++;
  }
  // مضرب الكمبيوتر
  float target = by + 1.5 - PH / 2.0;
  if (aiY < target - 1) aiY += 1.6;
  else if (aiY > target + 1) aiY -= 1.6;
  if (aiY < 16) aiY = 16;
  if (aiY > 62 - PH) aiY = 62 - PH;
  if (bvx > 0 && bx >= 118 && bx <= 124 && by + 3 > aiY && by < aiY + PH) {
    bvx = -bvx;
    bvy = ((by + 1.5) - (aiY + PH / 2.0)) / (PH / 2.0) * 2.2;
  }
  if (bx < 0) {
    lives--;
    if (lives <= 0) { die(); return; }
    pongServe(1);
  }
  if (bx > 128) { score += 5; pongServe(-1); }
}

void pongDraw() {
  char t[12];
  snprintf(t, sizeof(t), "PONG L:%d", lives);
  header(t, score);
  for (int y = 16; y < 62; y += 6) box(63, y, 2, 3);
  box(4, paddleY(), 3, PH);
  box(121, (int)aiY, 3, PH);
  box((int)bx, (int)by, 3, 3);
}

// ================= 3) Snake =================
// ايماءة: حرّك يدك نحو (اعلى/اسفل/يسار/يمين) من منتصف الكاميرا
const uint8_t SC = 25, SR = 9, CELL = 5, MAXLEN = 100;
uint8_t body[MAXLEN];
uint8_t slen, dir, wantDir, foodPos;
unsigned long lastStep;

void spawnFood() {
  while (true) {
    uint8_t p = random(SC * SR);
    bool ok = true;
    for (uint8_t i = 0; i < slen; i++) if (body[i] == p) { ok = false; break; }
    if (ok) { foodPos = p; return; }
  }
}

void snakeInit() {
  slen = 3;
  body[0] = 4 * SC + 12;
  body[1] = 4 * SC + 11;
  body[2] = 4 * SC + 10;
  dir = 0; wantDir = 0;
  spawnFood();
  lastStep = millis();
}

void snakeUpdate() {
  if (handPresent()) {
    int dx = (int)hx - 50, dy = (int)hy - 50;
    if (abs(dx) > 16 || abs(dy) > 16) {
      uint8_t nd = (abs(dx) > abs(dy)) ? (dx > 0 ? 0 : 2) : (dy > 0 ? 1 : 3);
      if (nd != (uint8_t)((dir + 2) % 4)) wantDir = nd;
    }
  }
  unsigned long interval = max(80, 170 - (int)slen * 3);
  if (millis() - lastStep < interval) return;
  lastStep = millis();
  dir = wantDir;

  int x = body[0] % SC, y = body[0] / SC;
  if (dir == 0) x++; else if (dir == 1) y++; else if (dir == 2) x--; else y--;
  if (x >= SC) x = 0;
  if (x < 0) x = SC - 1;
  if (y >= SR) y = 0;
  if (y < 0) y = SR - 1;
  uint8_t np = y * SC + x;

  bool grow = (np == foodPos);
  uint8_t checkLen = grow ? slen : slen - 1;
  for (uint8_t i = 0; i < checkLen; i++) {
    if (body[i] == np) { die(); return; }
  }
  if (grow && slen < MAXLEN) slen++;
  for (uint8_t i = slen - 1; i > 0; i--) body[i] = body[i - 1];
  body[0] = np;
  if (grow) { score++; spawnFood(); }
}

void snakeDraw() {
  header("SNAKE", score);
  for (uint8_t i = 0; i < slen; i++) {
    int cx = body[i] % SC, cy = body[i] / SC;
    if (i == 0) box(1 + cx * CELL, 17 + cy * CELL, 5, 5);
    else box(1 + cx * CELL, 17 + cy * CELL, 4, 4);
  }
  int fcx = foodPos % SC, fcy = foodPos / SC;
  box(1 + fcx * CELL, 17 + fcy * CELL, 4, 4);
  u8g2.setDrawColor(0);
  box(2 + fcx * CELL, 18 + fcy * CELL, 2, 2);
  u8g2.setDrawColor(1);
}

// ================= 4) Shooter =================
// ايماءة: حرّك يدك يمين/يسار لتحريك السفينة (الاطلاق تلقائي)
const uint8_t NE = 5, NB = 4;
float ex[NE], ey[NE];
bool ealive[NE];
int bxs[NB], bys[NB];
bool balive[NB];
int shipX;
unsigned int nextSpawn;

void shootInit() {
  lives = 3; shipX = 60;
  for (uint8_t i = 0; i < NE; i++) ealive[i] = false;
  for (uint8_t i = 0; i < NB; i++) balive[i] = false;
  nextSpawn = frameNo + 20;
}

void shootUpdate() {
  if (handPresent()) {
    int target = mapPos(hx, 0, 119);
    int d = target - shipX;
    if (abs(d) <= 2) shipX = target; else shipX += d / 2;
  }
  // اطلاق تلقائي
  if (frameNo % 8 == 0) {
    for (uint8_t i = 0; i < NB; i++) {
      if (!balive[i]) { balive[i] = true; bxs[i] = shipX + 4; bys[i] = 54; break; }
    }
  }
  for (uint8_t i = 0; i < NB; i++) {
    if (balive[i]) { bys[i] -= 4; if (bys[i] < 16) balive[i] = false; }
  }
  // ظهور الاعداء
  if ((int)(frameNo - nextSpawn) >= 0) {
    for (uint8_t i = 0; i < NE; i++) {
      if (!ealive[i]) { ealive[i] = true; ex[i] = random(0, 120); ey[i] = 17; break; }
    }
    int d = 40 - score / 3;
    if (d < 12) d = 12;
    nextSpawn = frameNo + d;
  }
  float spd = 0.5 + score * 0.01;
  if (spd > 1.6) spd = 1.6;
  for (uint8_t i = 0; i < NE; i++) {
    if (!ealive[i]) continue;
    ey[i] += spd;
    for (uint8_t j = 0; j < NB; j++) {
      if (balive[j] && bxs[j] >= ex[i] - 1 && bxs[j] <= ex[i] + 8 &&
          bys[j] >= ey[i] && bys[j] <= ey[i] + 6) {
        ealive[i] = false; balive[j] = false; score++;
        break;
      }
    }
    if (ealive[i] && ey[i] + 6 >= 56) {
      ealive[i] = false;
      lives--;
      if (lives <= 0) { die(); return; }
    }
  }
}

void shootDraw() {
  char t[14];
  snprintf(t, sizeof(t), "SHOOTER L:%d", lives);
  header(t, score);
  // السفينة
  box(shipX + 3, 56, 3, 3);
  box(shipX + 1, 58, 7, 2);
  box(shipX, 60, 9, 2);
  // الرصاص
  for (uint8_t i = 0; i < NB; i++) if (balive[i]) box(bxs[i], bys[i], 1, 3);
  // الاعداء
  for (uint8_t i = 0; i < NE; i++) {
    if (!ealive[i]) continue;
    int x = (int)ex[i], y = (int)ey[i];
    box(x + 1, y, 6, 3);
    box(x, y + 2, 8, 2);
    box(x + 1, y + 4, 2, 2);
    box(x + 5, y + 4, 2, 2);
    u8g2.setDrawColor(0);
    px(x + 2, y + 1);
    px(x + 5, y + 1);
    u8g2.setDrawColor(1);
  }
}

// ================= القائمة =================
const char* const MENU_NAMES[4] = {"1 Flappy Bird", "2 Pong", "3 Snake", "4 Shooter"};

void menuUpdate() {
  if (handPresent() && hf >= 1 && hf <= 4 && held(hf, 800)) enterMode(hf);
}

void menuDraw() {
  u8g2.setFont(u8g2_font_5x7_tr);
  u8g2.setDrawColor(1);
  u8g2.drawStr(0, 10, "GESTURE GAMES");
  if (!handPresent()) {
    u8g2.drawStr(86, 10, "NO HAND");
  } else {
    char b[8];
    snprintf(b, sizeof(b), "HAND %d", hf);
    u8g2.drawStr(86, 10, b);
  }
  for (uint8_t i = 0; i < 4; i++) {
    int base = 27 + i * 10;
    if (handPresent() && hf == i + 1) {
      float prog = (millis() - holdStart) / 800.0;
      if (prog > 1) prog = 1;
      box(0, base - 8, (int)(prog * 128), 10);
      u8g2.setDrawColor(2);   // XOR: النص يظهر فوق الشريط
      u8g2.drawStr(4, base, MENU_NAMES[i]);
      u8g2.setDrawColor(1);
    } else {
      u8g2.drawStr(4, base, MENU_NAMES[i]);
    }
  }
}

// ================= شاشة الخسارة =================
void overUpdate() {
  if (millis() - overTime > 1200) {
    if (held(0, 600)) enterMode(mode);
    else if (held(5, 600)) enterMode(M_MENU);
  }
}

void overDraw() {
  u8g2.setDrawColor(0);
  box(8, 20, 112, 38);
  u8g2.setDrawColor(1);
  u8g2.drawFrame(8, 20, 112, 38);
  u8g2.setFont(u8g2_font_ncenB10_tr);
  centerText("GAME OVER", 34);
  u8g2.setFont(u8g2_font_5x7_tr);
  char b[24];
  snprintf(b, sizeof(b), "Score %d  Best %d", score, best[mode - 1]);
  centerText(b, 43);
  centerText("Fist=retry 5=menu", 54);
}

// ================= تشغيل الاوضاع =================
void enterMode(uint8_t m) {
  mode = m;
  over = false;
  score = 0;
  holdStart = millis();
  switch (m) {
    case M_FLAPPY: flappyInit(); break;
    case M_PONG:   pongInit();   break;
    case M_SNAKE:  snakeInit();  break;
    case M_SHOOT:  shootInit();  break;
    default: break;
  }
}

void setup() {
  Serial.begin(57600);
  u8g2.begin();
  randomSeed(analogRead(A0));
  enterMode(M_MENU);
}

void loop() {
  readSerial();
  if (goMenu) { goMenu = false; enterMode(M_MENU); }

  if (millis() - lastFrame < FRAME_MS) return;
  lastFrame = millis();
  frameNo++;

  // التحديث
  if (over) {
    overUpdate();
  } else {
    switch (mode) {
      case M_MENU:   menuUpdate();   break;
      case M_FLAPPY: flappyUpdate(); break;
      case M_PONG:   pongUpdate();   break;
      case M_SNAKE:  snakeUpdate();  break;
      case M_SHOOT:  shootUpdate();  break;
    }
  }

  // الرسم (page buffer)
  u8g2.firstPage();
  do {
    switch (mode) {
      case M_MENU:   menuDraw();   break;
      case M_FLAPPY: flappyDraw(); break;
      case M_PONG:   pongDraw();   break;
      case M_SNAKE:  snakeDraw();  break;
      case M_SHOOT:  shootDraw();  break;
    }
    if (over) overDraw();
  } while (u8g2.nextPage());
}
