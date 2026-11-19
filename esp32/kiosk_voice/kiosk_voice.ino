/*
  Kopi Pagi: ESP32-S3 voice unit for the self-service coffee kiosk.

  The ESP32 does no AI. Hold the button, speak, release:
    1. mic (INMP441, I2S) is recorded as 16 kHz / 16-bit / mono PCM into PSRAM
    2. "Sebentar ya, Kak" plays while the audio is POSTed to  SERVER_URL/api/device/<id>/turn
    3. the server runs Whisper -> LangGraph/Phi-4-mini -> Piper and answers with raw PCM
    4. the reply is streamed straight into the MAX98357A amplifier (I2S)

  Board: ESP32-S3 with PSRAM (e.g. DevKitC-1 N16R8).
  Arduino IDE: install "esp32 by Espressif Systems" core 3.x, then
    Tools > Board            : ESP32S3 Dev Module
    Tools > PSRAM            : OPI PSRAM   (QSPI PSRAM on N8R2 boards)
    Tools > Partition Scheme : any scheme that includes SPIFFS (e.g. "Default 4MB with spiffs")
  Edit config.h first.
*/
#include <WiFi.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <ESP_I2S.h>
#include "config.h"

I2SClass mic;
I2SClass spk;

static int16_t *recBuf = nullptr;      // recording, in PSRAM
static size_t recCap = 0;              // capacity in samples
static uint8_t *waitPcm = nullptr;     // "Sebentar ya, Kak" kept in PSRAM for instant playback
static size_t waitLen = 0;
static volatile bool fillerPlaying = false;

static const char *PROMPTS[] = {"greet", "wait", "retry", "new", "offline"};

// ------------------------------------------------------------------ LED (on-board RGB if present)
void led(uint8_t r, uint8_t g, uint8_t b) {
#ifdef RGB_BUILTIN
  rgbLedWrite(RGB_BUILTIN, r, g, b);
#endif
}
#define LED_IDLE()      led(0, 0, 8)     // dim blue
#define LED_REC()       led(40, 0, 0)    // red   = recording
#define LED_THINK()     led(30, 20, 0)   // amber = server working
#define LED_SPEAK()     led(0, 30, 0)    // green = speaking
#define LED_ERROR()     led(40, 0, 40)   // purple

// ------------------------------------------------------------------ helpers
String urlDecode(const String &s) {
  String out;
  out.reserve(s.length());
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '%' && i + 2 < s.length()) {
      char hex[3] = {s[i + 1], s[i + 2], 0};
      out += (char)strtol(hex, nullptr, 16);
      i += 2;
    } else {
      out += c;
    }
  }
  return out;
}

void addAuth(HTTPClient &http) {
  if (strlen(DEVICE_TOKEN)) http.addHeader("X-Device-Token", DEVICE_TOKEN);
}

void playSilence(uint16_t ms) {
  static const uint8_t zeros[512] = {0};
  size_t bytes = (size_t)SAMPLE_RATE * 2 * ms / 1000;
  while (bytes) {
    size_t n = bytes < sizeof(zeros) ? bytes : sizeof(zeros);
    spk.write(const_cast<uint8_t *>(zeros), n);  // core 3.0.x write() takes a non-const buffer
    bytes -= n;
  }
}

void playBuffer(const uint8_t *pcm, size_t len) {
  spk.write(const_cast<uint8_t *>(pcm), len & ~1u);
  playSilence(60);  // flush the DMA buffer so the last samples don't repeat
}

// Prompts are cached in flash so "offline" still plays when the server is down.
bool downloadPrompt(const char *name) {
  HTTPClient http;
  http.begin(String(SERVER_URL) + "/api/device/prompt/" + name);
  addAuth(http);
  http.setTimeout(HTTP_TIMEOUT_MS);
  int code = http.GET();
  if (code != 200) {
    Serial.printf("prompt %s: HTTP %d\n", name, code);
    http.end();
    return false;
  }
  String path = String("/") + name + ".pcm";
  File f = LittleFS.open(path, "w");
  if (!f) { http.end(); return false; }
  int written = http.writeToStream(&f);
  f.close();
  http.end();
  Serial.printf("prompt %s: %d bytes cached\n", name, written);
  return written > 0;
}

void playPrompt(const char *name) {
  File f = LittleFS.open(String("/") + name + ".pcm", "r");
  if (!f) { Serial.printf("prompt %s not cached\n", name); return; }
  LED_SPEAK();
  uint8_t buf[1024];
  while (int n = f.read(buf, sizeof(buf))) spk.write(buf, n & ~1);
  f.close();
  playSilence(60);
  LED_IDLE();
}

void loadWaitPrompt() {
  File f = LittleFS.open("/wait.pcm", "r");
  if (!f) return;
  waitLen = f.size();
  waitPcm = (uint8_t *)ps_malloc(waitLen);
  if (waitPcm) f.read(waitPcm, waitLen); else waitLen = 0;
  f.close();
}

// The filler phrase plays on core 0 while core 1 does the HTTP request.
void fillerTask(void *) {
  playBuffer(waitPcm, waitLen);
  fillerPlaying = false;
  vTaskDelete(nullptr);
}

void startFiller() {
  if (!waitPcm || !waitLen) return;
  fillerPlaying = true;
  xTaskCreatePinnedToCore(fillerTask, "filler", 4096, nullptr, 2, nullptr, 0);
}

void waitFiller() {
  while (fillerPlaying) delay(5);
}

// ------------------------------------------------------------------ recording
size_t recordWhileHeld() {
  int32_t raw[256];
  size_t n = 0;
  int32_t peak = 0;
  float prevIn = 0, prevOut = 0;  // DC-blocking high-pass (INMP441 has a small DC offset)

  // throw away what accumulated in the DMA buffers while we were idle
  for (int i = 0; i < 4; i++) mic.readBytes((char *)raw, sizeof(raw));

  while (digitalRead(BTN_TALK) == LOW && n < recCap) {
    size_t got = mic.readBytes((char *)raw, sizeof(raw)) / sizeof(int32_t);
    for (size_t i = 0; i < got && n < recCap; i++) {
      float x = (float)(raw[i] >> MIC_SHIFT);
      float y = x - prevIn + 0.995f * prevOut;
      prevIn = x;
      prevOut = y;
      int32_t s = (int32_t)y;
      if (s > 32767) s = 32767;
      if (s < -32768) s = -32768;
      if (abs(s) > peak) peak = abs(s);
      recBuf[n++] = (int16_t)s;
    }
  }
  Serial.printf("recorded %.2fs, peak %ld (aim for 3000-25000; tune MIC_SHIFT)\n", n / (float)SAMPLE_RATE, (long)peak);
  return n;
}

// ------------------------------------------------------------------ one conversational turn
bool sendTurn(size_t samples) {
  HTTPClient http;
  http.begin(String(SERVER_URL) + "/api/device/" + DEVICE_ID + "/turn");
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/octet-stream");
  addAuth(http);
  const char *keys[] = {"X-Status", "X-Transcript", "X-Reply", "X-Stage", "X-Total", "X-Items", "X-Order-Number"};
  http.collectHeaders(keys, 7);

  int code = http.POST((uint8_t *)recBuf, samples * sizeof(int16_t));
  if (code != 200) {
    Serial.printf("turn failed: HTTP %d %s\n", code, code < 0 ? http.errorToString(code).c_str() : "");
    http.end();
    return false;
  }

  Serial.println("----------------------------------------");
  Serial.printf("heard : %s\n", urlDecode(http.header("X-Transcript")).c_str());
  Serial.printf("reply : %s\n", urlDecode(http.header("X-Reply")).c_str());
  Serial.printf("cart  : %s\n", urlDecode(http.header("X-Items")).c_str());
  Serial.printf("total : Rp%s   stage: %s   order: %s\n", http.header("X-Total").c_str(),
                http.header("X-Stage").c_str(), http.header("X-Order-Number").c_str());

  // stream the PCM reply into the amplifier as it arrives
  WiFiClient *stream = http.getStreamPtr();
  int remaining = http.getSize();  // -1 if unknown
  uint8_t buf[2048];
  size_t carry = 0;                // an odd byte left over, so samples stay 16-bit aligned
  uint32_t lastData = millis();

  waitFiller();
  LED_SPEAK();
  while (http.connected() && (remaining > 0 || remaining == -1)) {
    size_t avail = stream->available();
    if (!avail) {
      if (millis() - lastData > 5000) break;
      delay(2);
      continue;
    }
    size_t want = sizeof(buf) - carry;
    if (avail < want) want = avail;
    if (remaining > 0 && (int)want > remaining) want = remaining;
    int r = stream->readBytes(buf + carry, want);
    if (r <= 0) continue;
    lastData = millis();
    if (remaining > 0) remaining -= r;
    size_t total = carry + r;
    size_t even = total & ~1u;
    spk.write(buf, even);
    carry = total - even;
    if (carry) buf[0] = buf[even];
  }
  playSilence(60);
  http.end();
  LED_IDLE();
  return true;
}

void newOrder() {
  HTTPClient http;
  http.begin(String(SERVER_URL) + "/api/device/" + DEVICE_ID + "/reset");
  addAuth(http);
  http.setTimeout(10000);
  int code = http.POST((uint8_t *)nullptr, 0);
  http.end();
  Serial.printf("new order: HTTP %d\n", code);
  playPrompt(code == 200 ? "new" : "offline");
}

// ------------------------------------------------------------------ setup / loop
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // lower latency
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Wi-Fi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
    delay(250);
    Serial.print('.');
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " connected: " + WiFi.localIP().toString() : " FAILED");
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(BTN_TALK, INPUT_PULLUP);
  if (BTN_NEW >= 0) pinMode(BTN_NEW, INPUT_PULLUP);
  led(0, 0, 30);

  if (!psramFound()) {
    Serial.println("No PSRAM! Enable it in Tools > PSRAM.");
    LED_ERROR();
    while (true) delay(1000);
  }
  recCap = (size_t)SAMPLE_RATE * MAX_REC_SECONDS;
  recBuf = (int16_t *)ps_malloc(recCap * sizeof(int16_t));

  mic.setPins(MIC_SCK, MIC_WS, -1, MIC_SD);
  if (!mic.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT))
    Serial.println("mic I2S init failed");
  spk.setPins(SPK_BCLK, SPK_LRC, SPK_DIN);
  if (!spk.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO))
    Serial.println("speaker I2S init failed");

  if (!LittleFS.begin(true)) Serial.println("LittleFS mount failed (check partition scheme)");
  connectWiFi();
  if (WiFi.status() == WL_CONNECTED)
    for (const char *p : PROMPTS) downloadPrompt(p);  // refresh the cached phrases
  loadWaitPrompt();

  playPrompt(WiFi.status() == WL_CONNECTED ? "greet" : "offline");
  LED_IDLE();
  Serial.println("Ready. Hold the TALK button and speak.");
}

void loop() {
  if (BTN_NEW >= 0 && digitalRead(BTN_NEW) == LOW) {
    delay(30);
    if (digitalRead(BTN_NEW) == LOW) {
      newOrder();
      while (digitalRead(BTN_NEW) == LOW) delay(10);
    }
  }

  if (digitalRead(BTN_TALK) == LOW) {
    delay(30);  // debounce
    if (digitalRead(BTN_TALK) != LOW) return;

    LED_REC();
    size_t samples = recordWhileHeld();
    if (samples < SAMPLE_RATE * 0.4) {  // a tap, not speech
      LED_IDLE();
      return;
    }

    connectWiFi();
    if (WiFi.status() != WL_CONNECTED) {
      LED_ERROR();
      playPrompt("offline");
      return;
    }

    LED_THINK();
    startFiller();
    if (!sendTurn(samples)) {
      waitFiller();
      LED_ERROR();
      playPrompt("offline");
    }
  }
  delay(5);
}
