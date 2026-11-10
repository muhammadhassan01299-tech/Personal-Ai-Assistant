"""Voice: speech output (edge-tts neural voices, pyttsx3 offline fallback) and speech input.

* Speaks Urdu with ur-PK-UzmaNeural, English with a configurable voice.
* Never overlaps: one speech queue + a lock; `stop()` interrupts instantly (barge-in / emergency stop).
* Audio is cached on disk, so repeated phrases (e.g. the greeting) play instantly and even work
  before Wi-Fi is up (after the first successful synthesis).
* Word-boundary timing from edge-tts drives the orb pulse, so the HUD reacts to the real voice.
* Microphone level is measured from the real input stream for the listening waves.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Callable

from .config import Settings, app_dir, IS_WIN

LEVEL_CB = Callable[[float], None]


class Speaker:
    def __init__(self, settings: Settings, on_state: Callable[[str], None] | None = None):
        self.settings = settings
        self.on_state = on_state or (lambda s: None)
        self.cache_dir = app_dir() / "tts_cache"
        self.cache_dir.mkdir(exist_ok=True)
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._stop = threading.Event()
        self._speaking = threading.Event()
        self._pending = 0                              # items queued or being synthesised/played
        self._plock = threading.Lock()
        self._mixer_ok = False
        self._words: list[tuple[float, float]] = []   # (start_s, end_s) of the clip now playing
        self._t0 = 0.0
        self._tts_fallback = None
        self.last_engine = ""
        self.last_error = ""
        threading.Thread(target=self._worker, daemon=True, name="rani-speaker").start()

    # ---------------------------------------------------------------- public
    def say(self, speech: str, lang: str = "ur", volume: float | None = None, wait: bool = False,
            allow_offline: bool = True) -> bool:
        """Queue speech. With wait=True returns True if it was actually spoken."""
        speech = re.sub(r"\s+", " ", speech or "").strip()
        if not speech:
            return False
        holder = {"ok": False}
        done = threading.Event() if wait else None
        with self._plock:
            self._pending += 1
        self._q.put((speech, lang, volume, done, allow_offline, holder))
        if done:
            done.wait(120)
        return holder["ok"]

    def stop(self) -> None:
        """Interrupt current speech and drop everything queued."""
        self._stop.set()
        try:
            while True:
                item = self._q.get_nowait()
                with self._plock:
                    self._pending = max(0, self._pending - 1)
                if item[3] is not None:                # never leave a wait=True caller hanging for 120 s
                    item[3].set()
        except queue.Empty:
            pass
        try:
            if self._mixer_ok:
                import pygame
                pygame.mixer.music.stop()
        except Exception:
            pass
        if self._tts_fallback is not None:
            try:
                self._tts_fallback.stop()
            except Exception:
                pass

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    @property
    def busy(self) -> bool:
        """Speaking now, OR something is queued / still being synthesised (so the mic must stay closed)."""
        return self._speaking.is_set() or self._pending > 0

    def pulse(self) -> float:
        """0..1 'voice energy' for the HUD, derived from word timings of the playing clip."""
        if not self._speaking.is_set():
            return 0.0
        t = time.time() - self._t0
        if not self._words:
            return 0.5 + 0.3 * abs(((t * 7) % 2) - 1)
        for s, e in self._words:
            if s <= t <= e:
                p = (t - s) / max(e - s, 0.05)
                return 0.45 + 0.55 * abs(((p * 2) % 2) - 1) ** 0.6
        return 0.12

    def audio_ready(self) -> bool:
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._mixer_ok = True
        except Exception as e:
            self.last_error = f"mixer: {e}"
            return False
        if IS_WIN:
            try:
                from .winapi import WindowsBackend
                return WindowsBackend().audio_ready()
            except Exception:
                return False
        return True

    def wait_until_audio_ready(self, timeout: float = 90.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.audio_ready():
                return True
            time.sleep(1.5)
        return False

    def list_voices(self) -> list[dict]:
        try:
            import edge_tts
            voices = asyncio.run(edge_tts.list_voices())
            return [{"name": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"]}
                    for v in voices if v["Locale"].startswith(("ur-", "en-IN", "en-US", "en-GB", "pa-"))]
        except Exception as e:
            self.last_error = f"list voices: {e}"
            return []

    # ---------------------------------------------------------------- worker
    def _worker(self):
        while True:
            speech, lang, volume, done, allow_offline, holder = self._q.get()
            self._stop.clear()
            try:
                holder["ok"] = bool(self._speak_one(speech, lang, volume, allow_offline))
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
            finally:
                self._speaking.clear()
                with self._plock:
                    self._pending = max(0, self._pending - 1)
                self.on_state("speaking_done")
                if done:
                    done.set()

    def _voice_for(self, lang: str) -> str:
        return self.settings.get("voice_ur" if lang == "ur" else "voice_en")

    def _speak_one(self, speech: str, lang: str, volume: float | None, allow_offline: bool = True) -> bool:
        vol = self.settings.get("volume") if volume is None else volume
        voice = self._voice_for(lang)
        rate = max(-50, min(50, int(self.settings.get("speech_rate"))))
        key = hashlib.sha1(f"{voice}|{rate}|{speech}".encode("utf-8")).hexdigest()[:20]
        mp3, meta = self.cache_dir / f"{key}.mp3", self.cache_dir / f"{key}.json"
        words: list[tuple[float, float]] = []
        if mp3.exists() and mp3.stat().st_size > 500:
            if meta.exists():
                try:
                    words = [tuple(w) for w in json.loads(meta.read_text())]
                except ValueError:
                    pass
        else:
            try:
                words = self._synth_edge(speech, voice, rate, mp3)
                meta.write_text(json.dumps(words))
            except Exception as e:  # offline / service error -> fall back to local SAPI voice
                self.last_error = f"edge-tts: {type(e).__name__}: {str(e)[:100]}"
                if self._stop.is_set() or not allow_offline:
                    return False
                self._speak_offline(speech, lang, vol)
                return True
        if self._stop.is_set():
            return False
        self._play(mp3, words, vol)
        self.last_engine = "edge-tts:" + voice
        return True

    def _synth_edge(self, text: str, voice: str, rate_pct: int, out: Path):
        import edge_tts
        words: list[tuple[float, float]] = []

        async def run():
            rate = f"{rate_pct:+d}%"
            try:
                comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
            except TypeError:                       # older edge-tts: always word boundaries, no argument
                comm = edge_tts.Communicate(text, voice, rate=rate)
            with open(out, "wb") as f:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                        s = chunk["offset"] / 1e7
                        words.append((s, s + chunk["duration"] / 1e7))
        try:
            asyncio.run(asyncio.wait_for(run(), 25))
        except Exception:
            out.unlink(missing_ok=True)
            raise
        if not out.exists() or out.stat().st_size < 500:
            out.unlink(missing_ok=True)
            raise RuntimeError("empty audio from edge-tts")
        return words

    def _play(self, mp3: Path, words, vol: float):
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        self._mixer_ok = True
        pygame.mixer.music.load(str(mp3))
        pygame.mixer.music.set_volume(max(0.0, min(1.0, vol)))
        self._words = words
        self._t0 = time.time()
        self._speaking.set()
        self.on_state("speaking")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy() and not self._stop.is_set():
            time.sleep(0.03)
        pygame.mixer.music.stop()
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass

    def _speak_offline(self, speech: str, lang: str, vol: float):
        """Offline fallback (Windows SAPI voices through pyttsx3). Quality/accent depends on installed voices."""
        import pyttsx3
        eng = pyttsx3.init()
        self._tts_fallback = eng
        voices = eng.getProperty("voices")
        want = "urdu" if lang == "ur" else "english"
        pick = next((v for v in voices if want in (v.name or "").lower() or
                     ("ur" if lang == "ur" else "en") in str(getattr(v, "languages", "")).lower()), None)
        if pick is None:   # prefer a female voice
            pick = next((v for v in voices if any(n in (v.name or "").lower() for n in ("zira", "hazel", "female"))), None)
        if pick:
            eng.setProperty("voice", pick.id)
        eng.setProperty("volume", max(0.0, min(1.0, vol)))
        eng.setProperty("rate", 175 + int(self.settings.get("speech_rate")))
        self._words = []
        self._t0 = time.time()
        self._speaking.set()
        self.on_state("speaking")
        eng.say(speech)
        eng.runAndWait()
        self.last_engine = "pyttsx3-offline"


class Listener:
    """Speech input.  Uses SpeechRecognition + PyAudio, Google Web Speech for recognition (online)."""

    def __init__(self, settings: Settings, on_level: LEVEL_CB | None = None):
        self.settings = settings
        self.on_level = on_level or (lambda v: None)
        self._sr = None
        self._mic = None
        self.available = False
        self.last_error = ""
        self._calibrated = False
        self._init()

    def _init(self):
        try:
            import speech_recognition as sr
            self._sr = sr
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.pause_threshold = 0.8
            self._mic = sr.Microphone()
            self.available = True
        except Exception as e:  # no mic / no PyAudio
            self.last_error = f"{type(e).__name__}: {e}"
            self.available = False

    def calibrate(self):
        if not self.available:
            return
        with self._mic as src:
            self.recognizer.adjust_for_ambient_noise(src, duration=0.8)
        self._calibrated = True

    def listen_once(self, timeout=6.0, phrase_limit=10.0, cancel: threading.Event | None = None):
        """Capture one phrase -> sr.AudioData or None."""
        if not self.available:
            return None
        sr = self._sr
        with self._mic as source:
            if not self._calibrated:                       # first use: measure the room noise once
                try:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                except Exception:
                    pass
                self._calibrated = True
            stream = source.stream
            orig = stream.read

            def read(size, *a, **k):
                data = orig(size, *a, **k)
                try:
                    import array
                    arr = array.array("h", data)
                    if arr:
                        peak = (sum(abs(x) for x in arr) / len(arr)) / 6000.0
                        self.on_level(min(1.0, peak))
                except Exception:
                    pass
                return data
            stream.read = read
            try:
                return self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            except sr.WaitTimeoutError:
                return None
            finally:
                stream.read = orig
                self.on_level(0.0)

    def transcribe(self, audio) -> tuple[str, str]:
        """Try each configured language; return (text, language_code)."""
        sr = self._sr
        for code in self.settings.get("stt_languages"):
            try:
                text = self.recognizer.recognize_google(audio, language=code)
                if text.strip():
                    return text.strip(), code
            except sr.UnknownValueError:
                continue
            except sr.RequestError as e:
                self.last_error = f"speech service: {e}"
                return "", ""
        return "", ""
