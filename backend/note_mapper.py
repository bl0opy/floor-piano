"""
Maps piano key indices to note names and frequencies.

Default: one octave (C4–C5, 8 white keys).
Notes cycle if more keys than available entries are requested.
"""

from typing import Dict, List, Optional

# One full octave of white keys, C4 to C5
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

# Two-octave chromatic scale (12 notes × 2) for extended keyboards
CHROMATIC_NOTES: List[Dict] = [
    {"name": "C3",  "frequency": 130.81, "label": "C3"},
    {"name": "Db3", "frequency": 138.59, "label": "C#3"},
    {"name": "D3",  "frequency": 146.83, "label": "D3"},
    {"name": "Eb3", "frequency": 155.56, "label": "D#3"},
    {"name": "E3",  "frequency": 164.81, "label": "E3"},
    {"name": "F3",  "frequency": 174.61, "label": "F3"},
    {"name": "Gb3", "frequency": 185.00, "label": "F#3"},
    {"name": "G3",  "frequency": 196.00, "label": "G3"},
    {"name": "Ab3", "frequency": 207.65, "label": "G#3"},
    {"name": "A3",  "frequency": 220.00, "label": "A3"},
    {"name": "Bb3", "frequency": 233.08, "label": "A#3"},
    {"name": "B3",  "frequency": 246.94, "label": "B3"},
    {"name": "C4",  "frequency": 261.63, "label": "C4"},
    {"name": "Db4", "frequency": 277.18, "label": "C#4"},
    {"name": "D4",  "frequency": 293.66, "label": "D4"},
    {"name": "Eb4", "frequency": 311.13, "label": "D#4"},
    {"name": "E4",  "frequency": 329.63, "label": "E4"},
    {"name": "F4",  "frequency": 349.23, "label": "F4"},
    {"name": "Gb4", "frequency": 369.99, "label": "F#4"},
    {"name": "G4",  "frequency": 392.00, "label": "G4"},
    {"name": "Ab4", "frequency": 415.30, "label": "G#4"},
    {"name": "A4",  "frequency": 440.00, "label": "A4"},
    {"name": "Bb4", "frequency": 466.16, "label": "A#4"},
    {"name": "B4",  "frequency": 493.88, "label": "B4"},
]

NAMED_MAPS = {
    "default": DEFAULT_NOTES,
    "chromatic": CHROMATIC_NOTES,
}


class NoteMapper:
    def __init__(self, notes: Optional[List[Dict]] = None):
        self._base = list(notes or DEFAULT_NOTES)
        self._active: List[Dict] = list(self._base)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_note_map(self, notes: List[Dict]) -> None:
        self._active = list(notes)

    def get_notes_for_key_count(self, num_keys: int) -> List[Dict]:
        """Return exactly num_keys entries, cycling the base map if needed."""
        src = self._base
        return [src[i % len(src)] for i in range(num_keys)]

    def get_note_for_key(self, key_index: int) -> Optional[Dict]:
        if 0 <= key_index < len(self._active):
            return self._active[key_index]
        return None

    def all_notes(self) -> List[Dict]:
        return list(self._active)
