// ===== Dino Game - Arduino Nano + OLED 7-pin (SPI) + U8g2 =====
// التحكم: حرف 'J' من البايثون = قفز / بدء / إعادة اللعبة
// التوصيل: CLK=D13, MOSI=D11, DC=D9, CS=D10, RES=D8

#include <Arduino.h>
#include <U8g2lib.h>
#include <SPI.h>

// ---- اختر السطر الذي اشتغل معك في تجربة Hello World (واحد فقط) ----
U8G2_SSD1306_128X64_NONAME_F_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 8);
//U8G2_SH1106_128X64_NONAME_F_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 8);

// ---- رسمة الديناصور 16x16 (1 = بكسل مضاء) ----
const uint16_t DINO_BODY[12] PROGMEM = {
  0b0000011111111000,
  0b0000011011111110,
  0b0000011111111100,
  0b0000011111111100,
  0b0000011111000000,
  0b1000111111001000,
  0b1101111111011000,
  0b1111111111000000,
  0b0111111111000000,
  0b0011111111000000,
  0b0001111111000000,
  0b0000111110000000
};
const uint16_t LEGS_A[4] PROGMEM = {
  0b0000110001100000,
  0b0000110001000000,
  0b0000110000000000,
  0b0000111000000000
};
const uint16_t LEGS_B[4] PROGMEM = {
  0b0000110001100000,
  0b0000100001100000,
  0b0000000001100000,
  0b0000000001110000
};

// ---- ثوابت اللعبة ----
const int GROUND_Y = 58;            // خط الأرض (المنطقة الزرقاء تبدأ من y=16)
const int DINO_X = 12;
const int DINO_H = 16;
const unsigned long FRAME_MS = 30;
const float JUMP_V = -7.0;
const float GRAVITY = 0.8;

enum State { WAITING, RUNNING, DEAD };
State state = WAITING;

struct Obstacle { float x; uint8_t w, h, type; };
Obstacle obs[2];

float dinoY, vy, speed, score, groundScroll;
float cloudX[2] = {40, 100};
bool onGround = true;
bool jumpRequest = false;
unsigned int hiScore = 0;
unsigned long lastFrame = 0, deathTime = 0;
unsigned int frameCount = 0;

// ---------- أدوات الرسم ----------
void drawSprite(int x, int y, const uint16_t* rows, int n) {
  for (int r = 0; r < n; r++) {
    uint16_t v = pgm_read_word(&rows[r]);
    for (int c = 0; c < 16; c++) {
      if (v & (0x8000 >> c)) u8g2.drawPixel(x + c, y + r);
    }
  }
}

void drawCactus(int x, int w, int h) {
  int top = GROUND_Y - h;
  int cx = x + w / 2 - 1;
  int ay = top + h / 2;
  u8g2.drawBox(cx, top, 3, h);                 // الجذع
  u8g2.drawBox(x, ay, cx - x + 1, 2);          // الذراع اليسرى أفقي
  u8g2.drawBox(x, ay - 4, 2, 6);               // الذراع اليسرى عمودي
  u8g2.drawBox(cx + 2, ay - 2, x + w - cx - 2, 2); // اليمنى أفقي
  u8g2.drawBox(x + w - 2, ay - 5, 2, 5);       // اليمنى عمودي
}

void drawObstacle(const Obstacle& o) {
  int x = (int)o.x;
  if (o.type == 2) {
    drawCactus(x, 7, o.h);
    drawCactus(x + 8, 7, o.h);
  } else {
    drawCactus(x, o.w, o.h);
  }
}

void centerText(const char* s, int y) {
  u8g2.drawStr((128 - u8g2.getStrWidth(s)) / 2, y, s);
}

void drawScene() {
  u8g2.clearBuffer();

  // النتيجة (في الشريط الأصفر)
  u8g2.setFont(u8g2_font_5x7_tr);
  char buf[20];
  snprintf(buf, sizeof(buf), "HI %05u %05u", hiScore, (unsigned int)score);
  u8g2.drawStr(128 - u8g2.getStrWidth(buf) - 2, 9, buf);

  // الغيوم
  for (int i = 0; i < 2; i++) {
    int cx = (int)cloudX[i];
    int cy = 24 + i * 8;
    u8g2.drawRBox(cx, cy, 14, 4, 1);
    u8g2.drawRBox(cx + 3, cy - 2, 8, 3, 1);
  }

  // الأرض
  u8g2.drawHLine(0, GROUND_Y, 128);
  for (int i = 0; i < 8; i++) {
    int gx = ((i * 23 + 18400 - (int)groundScroll) % 184) - 20;
    u8g2.drawHLine(gx, GROUND_Y + 2 + (i % 2) * 2, 2 + (i % 3));
  }

  // العوائق
  for (int i = 0; i < 2; i++) {
    if (obs[i].x < 128) drawObstacle(obs[i]);
  }

  // الديناصور
  int y = (int)dinoY;
  drawSprite(DINO_X, y, DINO_BODY, 12);
  bool legA = (!onGround) || ((frameCount / 4) % 2 == 0);
  drawSprite(DINO_X, y + 12, legA ? LEGS_A : LEGS_B, 4);
}

// ---------- منطق اللعبة ----------
void setObstacle(int i, float x) {
  uint8_t t = random(3);
  obs[i].type = t;
  obs[i].w = (t == 0) ? 7 : (t == 1) ? 9 : 15;
  obs[i].h = (t == 1) ? 16 : 12;
  obs[i].x = x;
}

void resetGame() {
  dinoY = GROUND_Y - DINO_H;
  vy = 0;
  onGround = true;
  speed = 3.0;
  score = 0;
  groundScroll = 0;
  setObstacle(0, 190);
  setObstacle(1, 190 + 110);
}

bool checkHit() {
  int dx1 = DINO_X + 3, dx2 = DINO_X + 14;
  int dy1 = (int)dinoY + 2, dy2 = (int)dinoY + DINO_H - 1;
  for (int i = 0; i < 2; i++) {
    int ox1 = (int)obs[i].x + 1;
    int ox2 = (int)obs[i].x + obs[i].w - 1;
    int oy1 = GROUND_Y - obs[i].h + 1;
    int oy2 = GROUND_Y;
    if (dx1 < ox2 && dx2 > ox1 && dy1 < oy2 && dy2 > oy1) return true;
  }
  return false;
}

void updateGame() {
  // القفز
  if (jumpRequest && onGround) {
    vy = JUMP_V;
    onGround = false;
  }
  if (!onGround) {
    dinoY += vy;
    vy += GRAVITY;
    if (dinoY >= GROUND_Y - DINO_H) {
      dinoY = GROUND_Y - DINO_H;
      vy = 0;
      onGround = true;
    }
  }

  // السرعة تزداد مع النتيجة
  speed = 3.0 + score / 200.0;
  if (speed > 5.5) speed = 5.5;

  // العوائق
  for (int i = 0; i < 2; i++) {
    obs[i].x -= speed;
    if (obs[i].x + obs[i].w < 0) {
      float farthest = max(obs[0].x, obs[1].x);
      float gap = 90 + speed * 8;
      float nx = max(128.0f, farthest + gap) + random(0, 50);
      setObstacle(i, nx);
    }
  }

  // الأرض والغيوم والنتيجة
  groundScroll += speed;
  for (int i = 0; i < 2; i++) {
    cloudX[i] -= speed * 0.25;
    if (cloudX[i] < -16) cloudX[i] = 128 + random(0, 40);
  }
  score += 0.25;

  if (checkHit()) {
    state = DEAD;
    deathTime = millis();
    if ((unsigned int)score > hiScore) hiScore = (unsigned int)score;
  }
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(9600);
  u8g2.begin();
  randomSeed(analogRead(A0));
  resetGame();
  state = WAITING;
}

void loop() {
  // اقرأ كل ما وصل من البايثون
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'J' || c == 'R') jumpRequest = true;
  }

  if (millis() - lastFrame < FRAME_MS) return;
  lastFrame = millis();
  frameCount++;

  if (state == WAITING) {
    if (jumpRequest) { resetGame(); state = RUNNING; }
    drawScene();
    u8g2.setFont(u8g2_font_5x7_tr);
    centerText("Raise hand to start", 36);
    u8g2.sendBuffer();

  } else if (state == RUNNING) {
    updateGame();
    drawScene();
    u8g2.sendBuffer();

  } else { // DEAD
    if (jumpRequest && millis() - deathTime > 800) {
      resetGame();
      state = RUNNING;
    }
    drawScene();
    u8g2.setDrawColor(0);
    u8g2.drawBox(10, 22, 108, 30);
    u8g2.setDrawColor(1);
    u8g2.drawFrame(10, 22, 108, 30);
    u8g2.setFont(u8g2_font_ncenB10_tr);
    centerText("GAME OVER", 38);
    u8g2.setFont(u8g2_font_5x7_tr);
    centerText("Raise hand to retry", 49);
    u8g2.sendBuffer();
  }

  jumpRequest = false;
}
