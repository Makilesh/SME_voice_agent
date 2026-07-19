import os
import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uuid
from voice_handler import STTHandler, TTSHandler
from rag_pipeline import RAGPipeline
import redis
# from twilio.rest import Client  # Optional
from fastapi.staticfiles import StaticFiles


load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="."), name="static")

# Init components
stt_handler = STTHandler()
tts_handler = TTSHandler()
rag_pipeline = RAGPipeline()
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)

def _get_session_history_sync(session_id: str) -> list:
    history_json = redis_client.get(f"session:{session_id}")
    return json.loads(history_json) if history_json else []

def _update_session_history_sync(session_id: str, user_input: str, response: str):
    history = _get_session_history_sync(session_id)
    history.append({"input": user_input, "output": response})
    if len("".join([h["input"] + h["output"] for h in history])) > 8000:  # Token approx
        history = summarize_history(history)  # Implement summarization
    redis_client.set(f"session:{session_id}", json.dumps(history))

async def get_session_history(session_id: str) -> list:
    return await asyncio.to_thread(_get_session_history_sync, session_id)

async def update_session_history(session_id: str, user_input: str, response: str):
    await asyncio.to_thread(_update_session_history_sync, session_id, user_input, response)

@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())  # Simple user_id; improve for prod
    try:
        while True:
            # Receive audio chunk
            data = await websocket.receive_bytes()
            # STT streaming
            transcript, lang = await stt_handler.stream_transcribe(data)
            print(f"Received audio bytes: {len(data)}, Transcript: '{transcript}', Lang: {lang}")  # Log
            if transcript:
                # Get context from Redis
                history = await get_session_history(session_id)
                # RAG + LLM
                context = rag_pipeline.retrieve_and_generate(transcript, history, lang)
                print(f"RAG Response: '{context['response'][:100]}...'")  # Log
                # TTS
                audio = await tts_handler.synthesize(context["response"], lang)
                await websocket.send_bytes(audio)
                # Update history
                await update_session_history(session_id, transcript, context["response"])
                # Handle interruption: if new audio comes mid-TTS, pause (async task)
                if await stt_handler.is_interrupting():
                    await tts_handler.pause()
    except WebSocketDisconnect:
        pass

def summarize_history(history: list) -> list:
    # Use Grok to summarize; placeholder
    return history[-4:]  # Simple truncate

# # Optional Twilio integration
# @app.post("/call")
# async def start_call(to: str, from_: str):
#     client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
#     call = client.calls.create(
#         twiml='<Response><Start><Stream url="wss://yourdomain.com/ws/audio"/></Start></Response>',
#         to=to,
#         from_=from_
#     )
#     return {"call_sid": call.sid}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
