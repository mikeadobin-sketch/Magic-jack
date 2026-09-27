"""DTMF helpers: in-band tone synthesis (for SIP) and TwiML scripts (for Twilio)."""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

from .config import Job

SAMPLE_RATE = 8000

_ROWS = {"1": 697, "2": 697, "3": 697, "4": 770, "5": 770, "6": 770,
         "7": 852, "8": 852, "9": 852, "*": 941, "0": 941, "#": 941}
_COLS = {"1": 1209, "2": 1336, "3": 1477, "4": 1209, "5": 1336, "6": 1477,
         "7": 1209, "8": 1336, "9": 1477, "*": 1209, "0": 1336, "#": 1477}


def tone(digit: str, duration: float = 0.15, amplitude: float = 0.45) -> bytes:
    """8 kHz, 8-bit unsigned linear PCM of a single DTMF digit."""
    lo, hi = _ROWS[digit], _COLS[digit]
    n = int(SAMPLE_RATE * duration)
    out = bytearray(n)
    for i in range(n):
        t = i / SAMPLE_RATE
        s = amplitude * 0.5 * (math.sin(2 * math.pi * lo * t) + math.sin(2 * math.pi * hi * t))
        out[i] = max(0, min(255, int(128 + 127 * s)))
    return bytes(out)


def silence(duration: float) -> bytes:
    return bytes([128]) * int(SAMPLE_RATE * duration)


def _half_seconds(seconds: float) -> int:
    return max(0, round(seconds / 0.5))


def twiml(job: Job) -> str:
    """Build a TwiML script that waits and plays each step's digits.

    Twilio's <Pause> takes whole seconds; inside <Play digits> each 'w' is a
    0.5 s pause, so sub-second waits and digit gaps are rounded to 0.5 s.
    """
    parts = ["<Response>"]
    for step in job.steps:
        whole = int(step.wait)
        if whole >= 1:
            parts.append(f'<Pause length="{whole}"/>')
        lead = "w" * _half_seconds(step.wait - whole)
        gap = "w" * _half_seconds(step.digit_gap)
        parts.append(f'<Play digits="{escape(lead + gap.join(step.digits))}"/>')
    if job.hangup_after >= 1:
        parts.append(f'<Pause length="{int(job.hangup_after)}"/>')
    parts.append("<Hangup/></Response>")
    return "".join(parts)
