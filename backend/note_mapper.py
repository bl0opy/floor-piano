"""
Note frequency tables for the floor piano.

ALL_NOTES  : C2–C6 chromatic (49 notes) — used for per-region note selection.
DEFAULT_NOTES / CHROMATIC_NOTES kept for backward compatibility.
"""

from typing import Dict, List, Optional


def _build_all_notes() -> List[Dict]:
    """Generate C2–C6 chromatic using equal-temperament math."""
    NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    # A4 = 440 Hz, MIDI 69
    A4_FREQ = 440.0
    A4_MIDI = 69
    notes = []
    for octave in range(2, 7):
        for semi, name in enumerate(NOTE_NAMES):
            if octave == 6 and name != "C":
                break
            midi = (octave + 1) * 12 + semi
            freq = A4_FREQ * (2 ** ((midi - A4_MIDI) / 12))
            full_name = f"{name}{octave}"
            notes.append({"name": full_name, "frequency": round(freq, 2), "label": full_name})
    return notes


ALL_NOTES: List[Dict] = _build_all_notes()
ALL_NOTES_BY_NAME: Dict[str, Dict] = {n["name"]: n for n in ALL_NOTES}


# ---------------------------------------------------------------------------
# Legacy tables (kept for backward compat / audio preload)
# ---------------------------------------------------------------------------

DEFAULT_NOTES: List[Dict] = [
    {"name": "C4",  "frequency": 261.63, "label": "C4"},
    {"name": "D4",  "frequency": 293.66, "label": "D4"},
    {"name": "E4",  "frequency": 329.63, "label": "E4"},
    {"name": "F4",  "frequency": 349.23, "label": "F4"},
    {"name": "G4",  "frequency": 392.00, "label": "G4"},
    {"name": "A4",  "frequency": 440.00, "label": "A4"},
    {"name": "B4",  "frequency": 493.88, "label": "B4"},
    {"name": "C5",  "frequency": 523.25, "label": "C5"},
]

CHROMATIC_NOTES: List[Dict] = [
    {"name": "C3",  "frequency": 130.81, "label": "C3"},
    {"name": "C#3", "frequency": 138.59, "label": "C#3"},
    {"name": "D3",  "frequency": 146.83, "label": "D3"},
    {"name": "D#3", "frequency": 155.56, "label": "D#3"},
    {"name": "E3",  "frequency": 164.81, "label": "E3"},
    {"name": "F3",  "frequency": 174.61, "label": "F3"},
    {"name": "F#3", "frequency": 185.00, "label": "F#3"},
    {"name": "G3",  "frequency": 196.00, "label": "G3"},
    {"name": "G#3", "frequency": 207.65, "label": "G#3"},
    {"name": "A3",  "frequency": 220.00, "label": "A3"},
    {"name": "A#3", "frequency": 233.08, "label": "A#3"},
    {"name": "B3",  "frequency": 246.94, "label": "B3"},
    {"name": "C4",  "frequency": 261.63, "label": "C4"},
    {"name": "C#4", "frequency": 277.18, "label": "C#4"},
    {"name": "D4",  "frequency": 293.66, "label": "D4"},
    {"name": "D#4", "frequency": 311.13, "label": "D#4"},
    {"name": "E4",  "frequency": 329.63, "label": "E4"},
    {"name": "F4",  "frequency": 349.23, "label": "F4"},
    {"name": "F#4", "frequency": 369.99, "label": "F#4"},
    {"name": "G4",  "frequency": 392.00, "label": "G4"},
    {"name": "G#4", "frequency": 415.30, "label": "G#4"},
    {"name": "A4",  "frequency": 440.00, "label": "A4"},
    {"name": "A#4", "frequency": 466.16, "label": "A#4"},
    {"name": "B4",  "frequency": 493.88, "label": "B4"},
]

NAMED_MAPS = {
    "default": DEFAULT_NOTES,
    "chromatic": CHROMATIC_NOTES,
}


class NoteMapper:
    """Legacy mapper kept for audio preloading compatibility."""

    def __init__(self, notes: Optional[List[Dict]] = None):
        self._base = list(notes or DEFAULT_NOTES)
        self._active: List[Dict] = list(self._base)

    def set_note_map(self, notes: List[Dict]) -> None:
        self._active = list(notes)

    def get_notes_for_key_count(self, num_keys: int) -> List[Dict]:
        src = self._base
        return [src[i % len(src)] for i in range(num_keys)]

    def get_note_for_key(self, key_index: int) -> Optional[Dict]:
        if 0 <= key_index < len(self._active):
            return self._active[key_index]
        return None

    def all_notes(self) -> List[Dict]:
        return list(self._active)
