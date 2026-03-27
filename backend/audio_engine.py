"""
Audio playback engine using pygame.mixer.

Generates piano-like additive-synthesis tones on demand and caches them.
If a real .wav sample file exists in audio/samples/<NoteName>.wav it is
loaded and used instead of the generated tone — so dropping in real piano
samples automatically upgrades the audio quality with no code changes.
"""

import threading
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pygame

SAMPLES_DIR = Path(__file__).parent.parent / "audio" / "samples"

SAMPLE_RATE = 44100
BIT_DEPTH = -16        # 16-bit signed
CHANNELS = 2           # stereo
BUFFER_SIZE = 512      # low-latency audio buffer
TONE_DURATION = 2.0    # seconds per generated tone
NUM_MIXER_CHANNELS = 16


def _generate_piano_tone(frequency: float, duration: float = TONE_DURATION) -> np.ndarray:
    """
    Additive synthesis: fundamental + 4 harmonics, piano-style ADSR envelope.
    Returns a (N, 2) int16 array suitable for pygame.sndarray.make_sound.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)

    # Harmonic series with decreasing amplitudes (simulate piano timbre)
    wave = (
        1.000 * np.sin(2 * np.pi * frequency * 1 * t) +
        0.500 * np.sin(2 * np.pi * frequency * 2 * t) +
        0.250 * np.sin(2 * np.pi * frequency * 3 * t) +
        0.125 * np.sin(2 * np.pi * frequency * 4 * t) +
        0.063 * np.sin(2 * np.pi * frequency * 5 * t)
    )
    wave /= np.max(np.abs(wave) + 1e-9)

    # ADSR envelope
    atk = int(0.005 * SAMPLE_RATE)   # 5 ms attack
    dec = int(0.080 * SAMPLE_RATE)   # 80 ms decay
    sus_lvl = 0.55
    rel = int(0.400 * SAMPLE_RATE)   # 400 ms release

    env = np.ones(n)
    env[:atk] = np.linspace(0.0, 1.0, atk)
    dec_end = atk + dec
    if dec_end < n:
        env[atk:dec_end] = np.linspace(1.0, sus_lvl, dec)
    sus_end = n - rel
    if sus_end > dec_end:
        env[dec_end:sus_end] = np.linspace(sus_lvl, sus_lvl * 0.4, sus_end - dec_end)
    if sus_end > 0:
        env[sus_end:] = np.linspace(env[max(0, sus_end - 1)], 0.0, n - sus_end)

    wave *= env

    # Encode at 85 % of full scale, leaving headroom for the mixer to sum
    # multiple simultaneous voices without clipping (set_volume below brings
    # the per-channel peak to ~13 900, so two notes at peak = ~27 800 < 32 767).
    mono = (wave * 32767 * 0.85).astype(np.int16)
    stereo = np.ascontiguousarray(np.column_stack([mono, mono]))
    return stereo


class AudioEngine:
    def __init__(self):
        self._ready = False
        self._cache: Dict[str, pygame.mixer.Sound] = {}
        self._active_channels: Dict[str, pygame.mixer.Channel] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        try:
            pygame.mixer.pre_init(
                frequency=SAMPLE_RATE,
                size=BIT_DEPTH,
                channels=CHANNELS,
                buffer=BUFFER_SIZE,
            )
            pygame.mixer.init()
            pygame.mixer.set_num_channels(NUM_MIXER_CHANNELS)
            self._ready = True
            print("[Audio] pygame.mixer ready")
            return True
        except Exception as e:
            print(f"[Audio] Init failed (audio will be silent): {e}")
            return False

    def shutdown(self) -> None:
        if self._ready:
            with self._lock:
                for channel in self._active_channels.values():
                    try:
                        channel.stop()
                    except Exception:
                        pass
                self._active_channels.clear()
            pygame.mixer.quit()
            self._ready = False

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def preload_notes(self, notes: list) -> None:
        """Pre-generate and cache all note sounds (call in background thread)."""
        for note in notes:
            self._get_sound(note["name"], note["frequency"])

    def play_note(self, note_name: str, frequency: float) -> bool:
        """Non-blocking. Returns True if the note was played."""
        return self.note_on(note_name, frequency)

    def note_on(self, note_name: str, frequency: float) -> bool:
        """Start (and hold) a note until note_off is called."""
        sound = self._get_sound(note_name, frequency)
        if sound is None:
            return False
        with self._lock:
            existing = self._active_channels.get(note_name)
            if existing is not None and existing.get_busy():
                return True
            if existing is not None and not existing.get_busy():
                self._active_channels.pop(note_name, None)
            try:
                # loops=-1 sustains the note; note_off controls release.
                channel = sound.play(loops=-1, fade_ms=8)
                if channel is None:
                    return False
                self._active_channels[note_name] = channel
                return True
            except Exception as e:
                print(f"[Audio] Play error for {note_name}: {e}")
                return False

    def note_off(self, note_name: str) -> bool:
        """Release a currently held note."""
        with self._lock:
            channel = self._active_channels.pop(note_name, None)
        if channel is None:
            return False
        try:
            channel.fadeout(80)
            return True
        except Exception as e:
            print(f"[Audio] Stop error for {note_name}: {e}")
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_sound(self, name: str, frequency: float) -> Optional[pygame.mixer.Sound]:
        if not self._ready:
            return None

        with self._lock:
            if name in self._cache:
                return self._cache[name]

            # Prefer a real .wav sample if present
            wav_path = SAMPLES_DIR / f"{name}.wav"
            if wav_path.exists():
                try:
                    sound = pygame.mixer.Sound(str(wav_path))
                    self._cache[name] = sound
                    print(f"[Audio] Loaded sample: {wav_path.name}")
                    return sound
                except Exception as e:
                    print(f"[Audio] Could not load sample {wav_path.name}: {e}")

            # Fall back to synthesised tone
            try:
                data = _generate_piano_tone(frequency)
                sound = pygame.sndarray.make_sound(data)
                # 0.50 × 0.85 encoding ≈ 13 900 peak per voice; two voices
                # sum to ~27 800 — safely below the 32 767 int16 ceiling.
                sound.set_volume(0.50)
                self._cache[name] = sound
                print(f"[Audio] Synthesised tone for {name} ({frequency:.1f} Hz)")
                return sound
            except Exception as e:
                print(f"[Audio] Synthesis failed for {name}: {e}")
                return None
