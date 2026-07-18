import asyncio
from google.cloud import speech_v1p1beta1 as speech
from google.cloud import texttospeech
from dotenv import load_dotenv
import io
import pyaudio
import wave
try:
    from langdetect import detect
except ImportError:
    def detect(text): return "en-IN"  # Fallback

load_dotenv()

class STTHandler:
    def __init__(self):
        self.client = speech.SpeechClient()
        self.config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-IN",  # Fallback
            enable_automatic_punctuation=True,
            enable_word_confidence=True,
            model="latest_long",
            enable_spoken_punctuation=True
        )
        self.streaming_config = speech.StreamingRecognitionConfig(config=self.config, interim_results=True)
        self.is_playing = False  # For interruption

    async def stream_transcribe(self, audio_data: bytes) -> tuple:
        # Simulate streaming; in prod, use async generator for chunks
        audio_content = speech.RecognitionAudio(content=audio_data)
        # For real-time: use StreamingRecognizeRequest
        request = speech.StreamingRecognizeRequest(audio_content=audio_content, config=self.config)
        responses = self.client.streaming_recognize(self.streaming_config, requests=[request])
        
        transcript = ""
        detected_lang = "en-IN"
        for response in responses:
            if response.results:
                result = response.results[0]
                if result.is_final:
                    transcript = result.alternatives[0].transcript
                    print(f"STT Transcript: '{transcript}'")  # Log for debug
                    # Lang detection: fallback to alternatives or external
                    detected_lang = self.detect_language(transcript)  # Implement
                    break
        return transcript, detected_lang

    def detect_language(self, text: str) -> str:
        # Simple heuristic or use langdetect lib (add to reqs if needed)
        if any(word in text.lower() for word in ["rupee", "crore", "lakh"]):  # Finance Indian terms
            return "en-IN"
        return "en-IN"  # Placeholder; integrate Google lang detect

    async def is_interrupting(self) -> bool:
        # Check audio energy threshold
        return self.is_playing  # Simplified; implement audio buffer in prod

class TTSHandler:
    def __init__(self):
        self.client = texttospeech.TextToSpeechClient()
        self.is_playing = False
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=24000, output=True)

    async def synthesize(self, text: str, lang: str = "en-IN") -> bytes:
        # Voice selection
        voice_name = f"{lang.split('-')[0]}-IN-Neural2-A"  # e.g., hi-IN-Neural2-A
        voice = texttospeech.VoiceSelectionParams(language_code=lang, name=voice_name)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        
        # SSML for prosody
        ssml = f'<speak><prosody rate="medium" pitch="default">{text}</prosody></speak>'
        response = self.client.synthesize_speech(
            input=texttospeech.SynthesisInput(ssml=ssml),
            voice=voice,
            audio_config=audio_config
        )
        print(f"TTS Synthesized for: '{text[:50]}...'")  # Log for debug
        self.is_playing = True
        # Play async
        asyncio.create_task(self.play_audio(response.audio_content))
        return response.audio_content

    async def play_audio(self, audio_content: bytes):
        wf = wave.open(io.BytesIO(audio_content), 'rb')
        data = wf.readframes(wf.getnframes())
        self.stream.write(data)
        self.is_playing = False

    async def pause(self):
        self.stream.stop_stream()
        self.is_playing = False

    def __del__(self):
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()
