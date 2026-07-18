# Meeting Copilot — invisible, real-time meeting assistant

A Parakeet-style desktop copilot for Teams / Meet / Zoom. It renders on a
**translucent overlay that is invisible to screen sharing and recording**,
live-transcribes the call with speaker separation, and — the #1 goal —
**shows a suggested text answer within ~1–2 s** whenever the other party asks
you something. It also keeps running notes/action-items and answers your own
typed/hotkey questions grounded in documents you upload.

> Pivoted from the original SME finance voice bot. The STT/LLM engine is reused
> and upgraded from [`voice_engine_MVP`](https://github.com/Makilesh/voice_engine_MVP).

## How it works

```
Windows system audio (loopback) ─┐
   = the other participants       ├─► RealtimeSTT (local faster-whisper) ─► transcript "THEM"
Your microphone ─────────────────┘                                     └─► transcript "YOU"
                                             │
        THEM asks a question ──► turn detector ──► Copilot:
              RAG (your docs) + transcript ──► Gemini FLASH instant draft (streamed)
                                            ──► Gemini 3 PRO refine (streamed) ──► overlay card
```

- **Invisibility:** the Electron overlay calls `setContentProtection(true)`, which on
  Windows 10 2004+ sets `WDA_EXCLUDEFROMCAPTURE` — the window is removed from every
  capture path (screen share, recording, screenshots) at the DWM level, while staying
  visible to you locally.
- **Speaker separation without a diarization model:** two audio channels →
  loopback = "THEM", mic = "YOU". The copilot only answers THEM, and stays quiet while
  YOU are talking.
- **Latency-first model routing** (`backend/core/models.py`): a fast Flash *draft* appears
  almost immediately, then a 3 Pro *refine* pass replaces it with a sharper answer.

## Requirements

- **Windows 10 (2004+) or 11** — required for the invisible-overlay + WASAPI loopback.
- **Python 3.11 / 3.12**
- **Node.js 18+** (for the Electron shell)
- A **Gemini API key** (https://aistudio.google.com/apikey)
- GPU strongly recommended for STT (faster-whisper). CPU works with the `fast` tier.

## Setup

```powershell
# 1) Python env (the bundled .venv is from another machine — recreate it)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) Install torch for your hardware FIRST
#    GPU (CUDA 12):
pip install torch --index-url https://download.pytorch.org/whl/cu121
#    or CPU only:
# pip install torch --index-url https://download.pytorch.org/whl/cpu

# 3) Rest of the backend
pip install -r requirements.txt

# 4) Config
copy .env.example .env   # then edit .env and set GEMINI_API_KEY

# 5) Electron shell
cd desktop
npm install
cd ..
```

## Run

Two options:

**A. Let Electron start everything (default):**
```powershell
cd desktop
npm start          # spawns the Python backend + opens the overlay
```

**B. Run backend and overlay separately (better for debugging):**
```powershell
# terminal 1
uvicorn backend.main:app --host 127.0.0.1 --port 8000
# terminal 2
cd desktop
set SPAWN_BACKEND=0
npm start
```

Click **Start** in the overlay (or it begins when you connect). Join a meeting,
play some audio, and confirm THEM/YOU transcript lines appear.

### Global shortcuts
| Shortcut | Action |
|---|---|
| `Ctrl+Shift+Space` | Show / hide the overlay |
| `Ctrl+Shift+X` | Toggle click-through (pass mouse to the meeting) |
| `Ctrl+Shift+A` | Force a suggestion on the latest question |
| `Ctrl+Shift+K` | Focus the ask box |
| `Ctrl+Shift+↑ / ↓` | Overlay opacity up / down |

### Upload context for grounded answers
- Drop a file via the API: `POST /ingest` (pdf/docx/txt), or
- Paste text: send `{"cmd":"ingest_text","text":"…"}` on the control socket.

## Debugging

```powershell
# List WASAPI loopback devices (confirm system-audio capture works)
python -m backend.audio.capture

# Backend health
curl http://127.0.0.1:8000/health
```

## Project layout

```
backend/
  main.py              FastAPI + /ws/control WebSocket
  orchestrator.py      capture → STT → turn-detect → copilot/notes wiring
  audio/capture.py     WASAPI loopback + mic → 16k mono PCM
  voice_engine/        reused from voice_engine_MVP (upgraded)
    stt_handler.py     dual-channel RealtimeSTT (feed_audio)
    llm_handler.py     Gemini streaming + per-task routing
  engine/              turn_detector, copilot, notes, qa
  rag/pipeline.py      local-embedding Chroma RAG over uploaded docs
  core/                models (routing), session (state)
desktop/               Electron overlay (main.js, preload.js, renderer/)
```

## Configuration knobs

- `STT_MODE` = `fast` (tiny.en) | `balanced` (small.en) | `accurate` (base.en)
- `STT_BACKEND` = `local` (default) | `gemini_live` (cloud STT; 15-min session cap)
- Model IDs: `GEMINI_MODEL_PRO`, `GEMINI_MODEL_FLASH`, `GEMINI_LIVE_MODEL`

## ⚠️ Security & ethics

- **Rotate your keys.** The old `.env` and `SME_service_acc.json` in this repo contain
  **live credentials** (Pinecone / OpenRouter / xAI / Google service account). Rotate them
  now and keep them out of git — `.gitignore` already excludes them, but committed history
  may still contain them.
- **Consent matters.** Recording/transcribing a meeting may require the other parties'
  consent depending on jurisdiction and platform policy. Using an interview/sales copilot
  may violate an employer's or platform's rules. Use responsibly; the overlay being hidden
  from screen share does **not** hide the process from the OS.

## Roadmap

- macOS support (ScreenCaptureKit/CoreAudio loopback + `NSWindow.sharingType=.none`)
- Optional TTS "voice-agent" mode (Kokoro/Cartesia already available in `voice_engine`)
- Post-meeting high-accuracy re-transcription + multi-speaker diarization pass
