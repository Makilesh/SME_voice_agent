import streamlit as st
import asyncio
import websockets
import pyaudio
import wave
from dotenv import load_dotenv

load_dotenv()

st.title("SME Voice Agent - Finance Expert")

# Lang selector
selected_lang = st.selectbox("Select Language", ["en-IN", "hi-IN", "ta-IN", "te-IN", "ml-IN", "kn-IN"])

# Audio recorder
st.audio("Record your voice query below.")
if st.button("Start Recording"):
    # PyAudio recorder (simplified; use streamlit-webrtc for prod)
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
    frames = []
    for _ in range(0, int(16000 / 1024 * 5)):  # 5s
        data = stream.read(1024)
        frames.append(data)
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    # Save to WAV
    wf = wave.open("temp_query.wav", 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(16000)
    wf.writeframes(b''.join(frames))
    wf.close()
    
    # Send to backend via WS
    uri = "ws://localhost:8000/ws/audio"
    async def send_audio():
        async with websockets.connect(uri) as websocket:
            with open("temp_query.wav", "rb") as f:
                await websocket.send(f.read())
            response_audio = await websocket.recv()
            st.audio(response_audio, format="audio/mp3")
    
    asyncio.run(send_audio())

# Chat history
if "messages" in st.session_state:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# Optional: Display KB sources (fetch from backend)
