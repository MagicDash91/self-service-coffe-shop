// ---- Kopi Pagi voice unit: edit these before flashing ----
#pragma once

// Wi-Fi (ESP32 supports 2.4 GHz only)
#define WIFI_SSID     "NAMA_WIFI"
#define WIFI_PASS     "PASSWORD_WIFI"

// The PC running the FastAPI backend (start it with --host 0.0.0.0, open port 8020 in Windows Firewall).
// Find the PC's address with `ipconfig` -> IPv4 Address.
#define SERVER_URL    "http://192.168.1.10:8020"
#define DEVICE_ID     "kiosk-1"          // letters, digits, - or _ ; one per unit
#define DEVICE_TOKEN  ""                 // must match DEVICE_TOKEN in backend/.env (empty = no auth)

// ---- Pins (ESP32-S3 DevKitC-1; any free GPIOs work, avoid 0, 3, 45, 46 = strapping pins) ----
// INMP441 microphone (L/R pin -> GND = left channel, VDD -> 3V3)
#define MIC_SCK   4
#define MIC_WS    5
#define MIC_SD    6
// MAX98357A amplifier (VIN -> 5V, GAIN floating = 9 dB, SD floating = (L+R)/2)
#define SPK_BCLK  15
#define SPK_LRC   16
#define SPK_DIN   7
// Buttons to GND (internal pull-ups used)
#define BTN_TALK  9                      // hold to talk
#define BTN_NEW   10                     // new order; set to -1 if you don't wire it

// ---- Audio ----
#define SAMPLE_RATE      16000
#define MAX_REC_SECONDS  12
#define MIC_SHIFT        14              // INMP441 gain: lower = louder (12..16). Check Serial "peak" values.
#define HTTP_TIMEOUT_MS  65000           // LLM turns can take a while; HTTPClient caps this at 65535
