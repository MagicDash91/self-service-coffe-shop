# ESP32 voice unit

A push-to-talk speaker box for the kiosk. The ESP32-S3 only records and plays audio. Whisper, Phi-4-mini
(LangGraph) and Piper all run on the backend PC, reached over Wi-Fi.

```
hold button ─► record 16 kHz PCM (PSRAM) ─► POST /api/device/kiosk-1/turn ─► server: Whisper → agent → Piper
release        "Sebentar ya, Kak" plays    ◄── raw 16 kHz PCM + X-Reply / X-Total headers ◄──┘
               reply streams to the speaker
```

## Parts

| Part | Notes |
|---|---|
| ESP32-S3 dev board **with PSRAM** | e.g. ESP32-S3-DevKitC-1 **N16R8**. A plain ESP32 has too little RAM for the recording. |
| INMP441 I2S microphone | |
| MAX98357A I2S amplifier + 4–8 Ω speaker (3 W) | |
| 1–2 push buttons | TALK (required), NEW ORDER (optional) |

## Wiring (defaults in `kiosk_voice/config.h`)

| INMP441 | ESP32-S3 | | MAX98357A | ESP32-S3 | | Button | ESP32-S3 |
|---|---|---|---|---|---|---|---|
| VDD | 3V3 | | VIN | 5V | | TALK | GPIO 9 ↔ GND |
| GND | GND | | GND | GND | | NEW ORDER | GPIO 10 ↔ GND |
| L/R | GND | | BCLK | GPIO 15 | | | |
| SCK | GPIO 4 | | LRC | GPIO 16 | | | |
| WS | GPIO 5 | | DIN | GPIO 7 | | | |
| SD | GPIO 6 | | GAIN, SD | leave open | | | |

The on-board RGB LED shows state: blue = ready, red = recording, amber = server working, green = speaking, purple = error.

## 1. Prepare the server (your PC)

```powershell
cd D:\Langsmith-main\prototype-selfservice\backend
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8020
```

- Use `--host 0.0.0.0`. With `127.0.0.1` the ESP32 can't reach the server.
- Allow port 8020 through Windows Firewall (run once, as admin):
  `netsh advfirewall firewall add rule name="Kopi kiosk 8020" dir=in action=allow protocol=TCP localport=8020`
- Note the PC's IPv4 address from `ipconfig`. The ESP32 and the PC must be on the same Wi-Fi/LAN.
- Optional: set `DEVICE_TOKEN=some-secret` in `backend/.env` and the same value in `config.h`.

Check from another device on the network: `http://<PC-IP>:8020/api/health`.

## 2. Flash the ESP32

1. Arduino IDE: Boards Manager → install **esp32 by Espressif Systems** (core **3.x**).
2. Open `kiosk_voice/kiosk_voice.ino` and edit `config.h`: Wi-Fi, `SERVER_URL` (`http://<PC-IP>:8020`), pins.
3. Tools → Board **ESP32S3 Dev Module**, PSRAM **OPI PSRAM**, a partition scheme **with SPIFFS**.
4. Upload, open Serial Monitor at 115200.

Or from the command line with `arduino-cli` (this exact command compiles cleanly against core 3.0.7, about 82% of the 1.3 MB app partition):

```
arduino-cli core install esp32:esp32@3.0.7
arduino-cli compile --fqbn "esp32:esp32:esp32s3:PSRAM=opi,PartitionScheme=default" kiosk_voice
arduino-cli upload  --fqbn "esp32:esp32:esp32s3:PSRAM=opi,PartitionScheme=default" -p COM5 kiosk_voice
```

Use `PSRAM=enabled` (QSPI) on N8R2 boards. Replace `COM5` with the port shown by `arduino-cli board list`.

On boot it connects to Wi-Fi and downloads the fixed phrases (greeting, "sebentar ya", "coba ulangi",
"pesanan baru", "sistem gangguan") into flash. Then it greets you. The "gangguan" phrase is stored on the
device, so it still plays when the server is down.

## 3. Use it

Hold TALK, say e.g. *"dua es kopi susu aren"*, and release. The Serial Monitor shows what the server heard,
the reply, the cart and the total:

```
heard : Dua es kopi susu aren.
reply : Oke Kak, 2x Kopi Susu Gula Aren dingin sudah masuk pesanan. Mau tambah ...
cart  : 2x Kopi Susu Gula Aren dingin
total : Rp56000   stage: ordering   order:
```

**Tuning the mic:** the Serial Monitor prints `peak` after each recording. Aim for 3000–25000. If it's lower, decrease
`MIC_SHIFT` (louder); if it's clipping at 32767, increase it.

## Without hardware

`backend/tools/device_sim.py` sends exactly what the ESP32 sends:

```powershell
cd backend
.\.venv\Scripts\python tools\device_sim.py --reset
.\.venv\Scripts\python tools\device_sim.py "saya mau dua caffe latte dingin"
.\.venv\Scripts\python tools\device_sim.py --wav rekaman.wav
```

Each reply is saved as `tools/reply_N.wav` so you can listen to what the speaker would play.

## Device API

| Endpoint | |
|---|---|
| `POST /api/device/{id}/turn` | body = raw s16le 16 kHz mono PCM (or a WAV). Returns raw PCM in the same format, plus headers `X-Status` (`ok` / `no_speech` / `too_short`), `X-Transcript`, `X-Reply`, `X-Items` (percent-encoded), `X-Stage`, `X-Total`, `X-Order-Number`, `X-Timings` |
| `POST /api/device/{id}/reset` | new order for this unit |
| `GET /api/device/{id}` | the unit's current session and cart, for a tablet showing the same order |
| `GET /api/device/prompt/{name}` | `greet`, `wait`, `retry`, `new`, `offline` as PCM |

Each unit id has its own session. After `DEVICE_IDLE_RESET_S` (default 180 s) without speech, the next
press starts a fresh order for the next customer. Volume of the server audio: `DEVICE_TTS_GAIN` (default 0.9).

## Limits

- One turn takes about 3 s STT + 5–10 s agent on this PC. The "sebentar ya" filler covers the start of the wait.
- `HTTPClient` timeouts cap at about 65 s. The first turn after a cold Ollama start can take longer, so warm the server up first.
- Payment still needs a screen (QRIS) or a cashier. Pair the unit with the tablet UI, or add an LCD that draws the QR.
- Plain HTTP on the LAN. Use `DEVICE_TOKEN` at least; use HTTPS/VPN for anything outside the shop network.
- The sketch has not been compiled here (no Arduino toolchain on this PC). Flash it and report any compile error.
