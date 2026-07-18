"""FastAPI server: single control WebSocket between the Electron overlay and the
meeting orchestrator.

Run:  uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("meeting-copilot")

app = FastAPI(title="Meeting Copilot")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Single active orchestrator (single-user desktop app).
_orch: Orchestrator | None = None


@app.get("/health")
async def health() -> dict:
    s = get_settings()
    return {"ok": True, "gemini": s.has_gemini, "stt_backend": s.stt_backend,
            "stt_mode": s.stt_mode}


@app.post("/ingest")
async def ingest(file: UploadFile) -> dict:
    """Upload a doc (pdf/docx/txt) into the RAG store for the active session."""
    if _orch is None:
        return {"ok": False, "error": "no active session"}
    suffix = os.path.splitext(file.filename or "doc.txt")[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        n = await asyncio.to_thread(_orch.ingest_doc, path)
        return {"ok": True, "chunks": n, "source": file.filename}
    finally:
        os.unlink(path)


@app.websocket("/ws/control")
async def control(ws: WebSocket) -> None:
    """Bidirectional channel: commands in, UI events out."""
    global _orch
    await ws.accept()
    send_lock = asyncio.Lock()

    async def emit(event: dict) -> None:
        async with send_lock:
            await ws.send_json(event)

    _orch = Orchestrator(emit)
    try:
        while True:
            msg = await ws.receive_json()
            await _handle(msg, _orch, emit)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("control ws error: %s", e)
    finally:
        if _orch:
            _orch.stop()
            _orch = None


async def _handle(msg: dict, orch: Orchestrator, emit) -> None:
    cmd = msg.get("cmd")
    if cmd == "start":
        orch.start(glossary=msg.get("glossary", ""), context_note=msg.get("context", ""))
        await emit({"type": "status", "text": "listening"})
    elif cmd == "stop":
        orch.stop()
        await emit({"type": "status", "text": "stopped"})
    elif cmd == "ask":
        await orch.ask(msg.get("text", ""), fast=bool(msg.get("fast")))
    elif cmd == "force_copilot":
        await orch.force_copilot()
    elif cmd == "set_auto_copilot":
        orch.set_auto_copilot(bool(msg.get("enabled", True)))
        await emit({"type": "status", "text": f"auto_copilot={msg.get('enabled')}"})
    elif cmd == "ingest_text":
        n = await asyncio.to_thread(orch._rag.ingest_text, msg.get("text", ""), "pasted")
        await emit({"type": "status", "text": f"ingested {n} chunks"})
    else:
        await emit({"type": "status", "text": f"unknown cmd: {cmd}"})


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("backend.main:app", host=s.host, port=s.port, reload=False)
