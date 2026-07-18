"""Dual-channel real-time STT built on RealtimeSTT (local faster-whisper).

Reused & upgraded from voice_engine_MVP/src/app/stt_handler.py. Key change: the
recorders run with ``use_microphone=False`` and are driven by external PCM via
``feed_audio()`` so we can transcribe TWO independent channels:

    them  ← WASAPI loopback (other participants)  → drives the copilot
    you   ← microphone (the user)                 → notes + "don't answer while I talk"

Each channel emits partials (live preview) and finals (committed sentences)
through callbacks supplied by the orchestrator. No 15-minute cap (fully local).
"""
from __future__ import annotations

import ctypes
import logging
import threading
from collections.abc import Callable

from RealtimeSTT import AudioToTextRecorder

logger = logging.getLogger(__name__)

_MODEL_BY_MODE = {"fast": "tiny.en", "balanced": "small.en", "accurate": "base.en"}


def _cuda_runtime_available() -> bool:
    """Instant DLL probe (no subprocess) — same trick as the MVP."""
    for dll in ("cudart64_12.dll", "cudart64_120.dll", "cublas64_12.dll"):
        try:
            ctypes.WinDLL(dll)
            return True
        except OSError:
            continue
    return False


class ChannelRecorder:
    """One RealtimeSTT recorder fed by external audio, for a single speaker channel."""

    def __init__(
        self,
        channel: str,
        mode: str,
        on_partial: Callable[[str, str], None],
        on_final: Callable[[str, str], None],
        initial_prompt: str = "",
    ) -> None:
        self.channel = channel
        self.on_partial = on_partial
        self.on_final = on_final
        self.model_name = _MODEL_BY_MODE.get(mode, "small.en")
        self._recorder: AudioToTextRecorder | None = None
        self._worker: threading.Thread | None = None
        self._running = threading.Event()
        self._initial_prompt = initial_prompt

        if _cuda_runtime_available():
            self._device, self._compute = "cuda", "float16"
        else:
            self._device, self._compute = "cpu", "int8"

    def start(self) -> None:
        def _partial(text: str) -> None:
            if text and text.strip():
                self.on_partial(self.channel, text.strip())

        self._recorder = AudioToTextRecorder(
            model=self.model_name,
            language="en",
            device=self._device,
            compute_type=self._compute,
            use_microphone=False,               # ← external audio via feed_audio()
            enable_realtime_transcription=True,
            on_realtime_transcription_update=_partial,
            realtime_model_type="tiny.en",      # cheap live preview; main model for finals
            realtime_processing_pause=0.1,
            # Turn-end tuning: ~0.5 s silence marks end of a spoken turn.
            post_speech_silence_duration=0.5,
            min_length_of_recording=0.2,
            min_gap_between_recordings=0.15,
            pre_recording_buffer_duration=0.3,
            silero_sensitivity=0.45,
            silero_use_onnx=True,
            webrtc_sensitivity=3,
            beam_size=1,
            initial_prompt=self._initial_prompt or None,
            spinner=False,
            level=logging.WARNING,
        )
        self._running.set()
        self._worker = threading.Thread(
            target=self._final_loop, name=f"stt-{self.channel}", daemon=True
        )
        self._worker.start()
        logger.info("🎤 STT[%s] started (model=%s, %s/%s)",
                    self.channel, self.model_name, self._device, self._compute)

    def _final_loop(self) -> None:
        """recorder.text() blocks until a full utterance is transcribed, then returns."""
        while self._running.is_set():
            try:
                text = self._recorder.text()  # processes fed audio; blocks per-utterance
            except Exception as e:
                if self._running.is_set():
                    logger.warning("STT[%s] text() error: %s", self.channel, e)
                continue
            if text and text.strip():
                self.on_final(self.channel, text.strip())

    def feed(self, pcm_16k_mono: bytes) -> None:
        if self._recorder is not None:
            try:
                self._recorder.feed_audio(pcm_16k_mono)
            except Exception as e:
                logger.debug("STT[%s] feed error: %s", self.channel, e)

    def stop(self) -> None:
        self._running.clear()
        try:
            if self._recorder:
                self._recorder.shutdown()
        except Exception:
            pass


class DualChannelSTT:
    """Convenience wrapper owning both channel recorders."""

    def __init__(
        self,
        mode: str,
        on_partial: Callable[[str, str], None],
        on_final: Callable[[str, str], None],
        glossary: str = "",
    ) -> None:
        self.them = ChannelRecorder("them", mode, on_partial, on_final, glossary)
        self.you = ChannelRecorder("you", mode, on_partial, on_final, glossary)

    def start(self) -> None:
        self.them.start()
        self.you.start()

    def feed_them(self, pcm: bytes) -> None:
        self.them.feed(pcm)

    def feed_you(self, pcm: bytes) -> None:
        self.you.feed(pcm)

    def stop(self) -> None:
        self.them.stop()
        self.you.stop()
