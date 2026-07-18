"""Dual-channel Windows audio capture → 16 kHz mono 16-bit PCM frames.

Channel "them" = WASAPI **loopback** (what the other participants say, coming
out of your speakers) via PyAudioWPatch.
Channel "you"  = the default microphone (WASAPI input).

Each channel runs on its own thread and pushes resampled PCM chunks into a
callback (the STT engine's ``feed_audio``). Format matches RealtimeSTT's
requirement: 16-bit signed mono, little-endian, 16000 Hz.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

try:
    import pyaudiowpatch as pyaudio
except Exception as e:  # pragma: no cover - import-time guard
    pyaudio = None
    _IMPORT_ERR = e

logger = logging.getLogger(__name__)

TARGET_RATE = 16000
CHUNK_MS = 20  # ~20 ms frames → low latency


def _resample_to_16k_mono(data: bytes, src_rate: int, src_channels: int) -> bytes:
    """Downmix to mono and resample to 16 kHz using linear interpolation.

    Linear resampling is cheap and more than adequate for speech STT.
    """
    audio = np.frombuffer(data, dtype=np.int16)
    if audio.size == 0:
        return b""
    if src_channels > 1:
        audio = audio.reshape(-1, src_channels).mean(axis=1).astype(np.int16)
    if src_rate != TARGET_RATE:
        n_out = int(round(audio.size * TARGET_RATE / src_rate))
        if n_out <= 0:
            return b""
        x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        audio = np.interp(x_new, x_old, audio.astype(np.float32)).astype(np.int16)
    return audio.tobytes()


class _ChannelStream(threading.Thread):
    def __init__(self, name: str, on_pcm: Callable[[bytes], None], loopback: bool):
        super().__init__(name=f"audio-{name}", daemon=True)
        self.channel = name
        self.on_pcm = on_pcm
        self.loopback = loopback
        self._stop = threading.Event()
        self._pa = None
        self._stream = None

    def _open_device(self):
        pa = pyaudio.PyAudio()
        if self.loopback:
            dev = pa.get_default_wasapi_loopback()  # provided by PyAudioWPatch
        else:
            dev = pa.get_default_input_device_info()
        rate = int(dev["defaultSampleRate"])
        channels = int(dev["maxInputChannels"]) or 1
        frames = int(rate * CHUNK_MS / 1000)
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=frames,
        )
        logger.info("🎧 [%s] %s @ %d Hz, %d ch (idx %s)",
                    self.channel, dev["name"], rate, channels, dev["index"])
        return pa, stream, rate, channels, frames

    def run(self) -> None:
        if pyaudio is None:
            logger.error("PyAudioWPatch not available: %s", _IMPORT_ERR)
            return
        try:
            self._pa, self._stream, rate, channels, frames = self._open_device()
        except Exception as e:
            logger.error("[%s] failed to open device: %s", self.channel, e)
            return
        while not self._stop.is_set():
            try:
                raw = self._stream.read(frames, exception_on_overflow=False)
            except Exception as e:
                logger.warning("[%s] read error: %s", self.channel, e)
                continue
            pcm = _resample_to_16k_mono(raw, rate, channels)
            if pcm:
                try:
                    self.on_pcm(pcm)
                except Exception as e:
                    logger.debug("[%s] on_pcm consumer error: %s", self.channel, e)
        self._cleanup()

    def _cleanup(self) -> None:
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
            if self._pa:
                self._pa.terminate()
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()


class DualChannelCapture:
    """Owns the mic + loopback threads and routes PCM to two consumers."""

    def __init__(
        self,
        on_them_pcm: Callable[[bytes], None],
        on_you_pcm: Callable[[bytes], None],
        capture_mic: bool = True,
    ) -> None:
        self._them = _ChannelStream("them", on_them_pcm, loopback=True)
        self._you = _ChannelStream("you", on_you_pcm, loopback=False) if capture_mic else None

    def start(self) -> None:
        self._them.start()
        if self._you:
            self._you.start()

    def stop(self) -> None:
        self._them.stop()
        if self._you:
            self._you.stop()


def list_devices() -> None:
    """Debug helper: print WASAPI devices and the default loopback."""
    if pyaudio is None:
        print("PyAudioWPatch not installed:", _IMPORT_ERR)
        return
    pa = pyaudio.PyAudio()
    print("Default loopback:", pa.get_default_wasapi_loopback()["name"])
    for info in pa.get_loopback_device_info_generator():
        print("  loopback:", info["index"], info["name"])
    pa.terminate()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    list_devices()
