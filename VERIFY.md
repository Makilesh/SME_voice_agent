# Verification Guide — Meeting Copilot

How to take this from "code written" to "working on a real call", in stages.
Each stage has a **command**, an **expected result**, and a **gate** — don't move
on until the gate passes. Stages 2 and 4 are the two genuinely risky ones.

---

## Current status (verified 2026-07-24)

| Check | Result |
|---|---|
| All backend modules compile | ✅ pass |
| `backend.main` imports, routes register | ✅ pass (`/health`, `/ingest`, `/ws/control`) |
| Backend boots + serves `/health` | ✅ pass |
| Turn-detector question heuristic | ✅ pass (8/8 cases) |
| Python deps (fastapi, genai, RealtimeSTT, chromadb, torch, faster-whisper) | ✅ installed |
| `PyAudioWPatch` (system-audio capture) | ❌ **missing** |
| `GEMINI_API_KEY` in `.env` | ❌ **missing** |
| `desktop/node_modules` (Electron) | ❌ **`npm install` not run** |
| GPU for STT | ⚠️ **CPU-only** (torch has no CUDA) |

**Verdict: not runnable end-to-end yet.** Three blockers, all in Step 0 below —
about 5 minutes of work. The backend itself is confirmed healthy.

---

## Step 0 — Clear the three blockers

```powershell
# 1. System-audio capture library (this is what hears the other participants)
pip install PyAudioWPatch

# 2. Add your Gemini key to .env  (get one: https://aistudio.google.com/apikey)
#    Add this line to .env:
#      GEMINI_API_KEY=your_key_here

# 3. Electron dependencies
cd desktop
npm install
cd ..
```

### ⚠️ Also do this: you are on CPU-only torch

`STT_MODE` is currently `balanced` (`small.en`), which on CPU will lag behind
real time and blow the latency budget. Pick one:

```powershell
# Option A (fastest fix) — use the small model in .env:
#   STT_MODE=fast
#
# Option B (better accuracy, if you have an NVIDIA GPU) — install CUDA torch:
pip uninstall -y torch
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

Confirm which you got:
```powershell
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

---

## Stage 1 — Backend health

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:
```bash
curl http://127.0.0.1:8000/health
```

**Expect:** `{"ok":true,"gemini":true,"stt_backend":"local","stt_mode":"fast"}`

**Gate:** `"gemini"` must be `true`. If it's `false`, `GEMINI_API_KEY` isn't being
read from `.env`.

---

## Stage 2 — System-audio (loopback) capture ⚠️ critical

This proves the app can hear **the other participants**, not just your mic. It is
the single most important thing to verify.

```bash
python -m backend.audio.capture
```

**Expect:** your default speakers/headset printed as the loopback device, e.g.
`Default loopback: Speakers (Realtek(R) Audio) [Loopback]`

**Gate:** if it prints `PyAudioWPatch not installed` → redo Step 0.1. If it finds
no loopback device, check that your output device is active (play something first)
and that you're on Windows 10 2004+.

**Real test:** play a YouTube video, then run Stage 3 and confirm the video's speech
shows up as `THEM`.

---

## Stage 3 — Live transcription (THEM / YOU separation)

Start the backend (Stage 1), then connect and start a session. Quickest way is the
overlay (Stage 4), but you can drive it directly:

```powershell
python -c @'
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8000/ws/control") as ws:
        await ws.send(json.dumps({"cmd":"start"}))
        while True:
            print(json.loads(await ws.recv()))
asyncio.run(main())
'@
```

Now **play a video** (→ should appear as `THEM`) and **talk into your mic**
(→ should appear as `YOU`).

**Expect:** a stream of
`{"type":"transcript","speaker":"them","text":"...","final":false}` then `final:true`.

**Gate:** both channels produce text, and they're labeled correctly. First run
downloads the Whisper model — allow a minute.

---

## Stage 4 — The invisibility test ⚠️ critical

```powershell
cd desktop
npm start
```

The overlay appears (translucent panel, top-left). Now prove it's invisible:

1. Start a **Teams / Meet / Zoom** call — or just open the Windows **Xbox Game Bar**
   recorder (`Win+G`) or Steps Recorder.
2. **Share your screen** / start recording.
3. Look at the shared or recorded output on a second device (or review the recording).

**Expect:** the overlay is **completely absent** from the shared/recorded view, while
still visible on your own monitor.

**Gate:** if it shows as a **black rectangle**, you're on Windows < 10 2004 — the OS
falls back to `WDA_MONITOR`. If it shows **fully**, `setContentProtection` failed;
check the Electron console.

**Re-test after:** hiding and re-showing (`Ctrl+Shift+Space`), and after dragging the
window to a second monitor. These are the known regression paths.

---

## Stage 5 — The full copilot loop (the actual product)

With the overlay running and a real (or mock) call in progress:

1. Have someone ask you a question out loud on the call — e.g.
   *"Can you walk me through how you'd design a rate limiter?"*
2. Watch the **Suggested answer** card.

**Expect:**
- A greyed *italic* draft appears within roughly **1–1.5 s** (Flash instant draft).
- It is then **replaced** by the refined, non-italic answer (Gemini 3 Pro), streaming
  to completion by ~2–3 s.

**Gate:** first words on screen in under ~2 s. If it's much slower, the usual cause is
CPU STT — see the CPU note in Step 0.

### Also exercise
| What | How | Expect |
|---|---|---|
| Suppression while you talk | Talk, and have them ask a question within 2 s | **No** auto-suggestion (by design) |
| Force a suggestion | `Ctrl+Shift+A` | Card generated for the last question |
| On-demand Q&A | `Ctrl+Shift+K`, type a question, Enter | Green-bordered answer card |
| Click-through | `Ctrl+Shift+X` | Clicks pass through to the meeting behind |
| Notes | Let it run ~6 finalized utterances | Notes panel fills with summary + action items |

### Grounded answers (RAG)
```bash
curl -F "file=@C:/path/to/your_resume.pdf" http://127.0.0.1:8000/ingest
```
**Expect:** `{"ok":true,"chunks":N,...}`. Then have them ask something answerable only
from that document — the answer should cite its content rather than invent something.

---

## Measuring latency properly

The backend logs per-stage timings. To get a clean number, watch the timestamps
between the `transcript ... final:true` event and the first `copilot ... stage:"draft"`
delta on the control socket. That interval is your **time-to-first-word**; target is
**under 1.5 s**.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `"gemini": false` in `/health` | Key not in `.env` | Add `GEMINI_API_KEY=…`, restart backend |
| No `THEM` text, only `YOU` | Loopback device not captured | Re-run Stage 2; ensure audio is actually playing |
| Overlay is a black box in screen share | Windows < 10 2004 | Update Windows |
| Overlay visible in screen share | `setContentProtection` failed | Check Electron console; re-assert after `show()` |
| Transcription lags far behind speech | CPU STT with `small.en` | `STT_MODE=fast`, or install CUDA torch |
| Suggestions never fire | Question heuristic didn't match, or you spoke recently | Use `Ctrl+Shift+A` to force |
| Backend won't start: `ModuleNotFoundError` | Missing dep | `pip install -r requirements.txt` |
| `error: Microsoft Visual C++ 14.0 or greater is required` building `chroma-hnswlib` | Old `chromadb==0.6.3` pinned a C++ package with no cp312 wheel | Already fixed — `requirements.txt` now uses `chromadb==1.5.9` (prebuilt wheel, no compiler). Just re-run `pip install -r requirements.txt`. |

---

## Before you use this on a real call

- **Rotate the leaked credentials.** `.env` and `SME_service_acc.json` contain live
  Pinecone / OpenRouter / xAI / Google service-account keys. They're gitignored now,
  but git history may still hold them.
- **Consent.** Transcribing a meeting may legally require the other parties' consent,
  and interview/sales copilot use may breach platform or employer policy. The overlay
  hides from screen capture — it does **not** hide the process from the OS.
