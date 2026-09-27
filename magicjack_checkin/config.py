"""Load and validate a check-in job from a TOML file."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VALID_DIGITS = re.compile(r"^[0-9*#]+$")
BACKENDS = ("twilio", "sip", "dry-run")


class ConfigError(ValueError):
    pass


@dataclass
class Step:
    """Wait `wait` seconds, then key in `digits`, pausing `digit_gap` between each."""

    digits: str
    wait: float = 0.0
    digit_gap: float = 0.25

    @property
    def duration(self) -> float:
        return self.wait + max(len(self.digits) - 1, 0) * self.digit_gap


@dataclass
class Schedule:
    tz: ZoneInfo
    start: datetime | None = None  # earliest time to place the call (None = now)
    end: datetime | None = None  # stop retrying after this time
    retry_interval: float = 60.0
    max_attempts: int = 3


@dataclass
class Job:
    number: str
    backend: str
    steps: list[Step]
    schedule: Schedule
    hangup_after: float = 3.0  # linger after the last digit so the system registers it
    twilio: dict = field(default_factory=dict)
    sip: dict = field(default_factory=dict)

    @property
    def script_duration(self) -> float:
        return sum(s.duration for s in self.steps) + self.hangup_after


def _parse_time(value: str | None, tz: ZoneInfo, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError as e:
        raise ConfigError(f"schedule.{name}: {e}") from None
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def _resolve_secrets(section: dict) -> dict:
    """Keys ending in `_env` name an environment variable holding the real value."""
    out = {}
    for key, value in section.items():
        if key.endswith("_env"):
            real = key[: -len("_env")]
            if value not in os.environ:
                raise ConfigError(f"environment variable {value!r} (for {real}) is not set")
            out[real] = os.environ[value]
        else:
            out[key] = value
    return out


def parse(data: dict, backend_override: str | None = None) -> Job:
    call = data.get("call", {})
    number = str(call.get("number", "")).strip()
    if not number:
        raise ConfigError("call.number is required")

    backend = backend_override or call.get("backend", "dry-run")
    if backend not in BACKENDS:
        raise ConfigError(f"call.backend must be one of {BACKENDS}, got {backend!r}")

    raw_steps = data.get("steps", [])
    if not raw_steps:
        raise ConfigError("at least one [[steps]] entry is required")
    steps = []
    for i, raw in enumerate(raw_steps, 1):
        digits = str(raw.get("digits", "")).replace(" ", "").replace("-", "")
        if not VALID_DIGITS.match(digits):
            raise ConfigError(f"steps[{i}].digits must contain only 0-9, * and #: {digits!r}")
        step = Step(
            digits=digits,
            wait=float(raw.get("wait", 0)),
            digit_gap=float(raw.get("digit_gap", 0.25)),
        )
        if step.wait < 0 or step.digit_gap < 0:
            raise ConfigError(f"steps[{i}]: wait and digit_gap must be >= 0")
        steps.append(step)

    sched = data.get("schedule", {})
    tz = ZoneInfo(sched.get("timezone", "UTC"))
    schedule = Schedule(
        tz=tz,
        start=_parse_time(sched.get("start"), tz, "start"),
        end=_parse_time(sched.get("end"), tz, "end"),
        retry_interval=float(sched.get("retry_interval", 60)),
        max_attempts=int(sched.get("max_attempts", 3)),
    )
    if schedule.start and schedule.end and schedule.end <= schedule.start:
        raise ConfigError("schedule.end must be after schedule.start")
    if schedule.max_attempts < 1:
        raise ConfigError("schedule.max_attempts must be >= 1")

    job = Job(
        number=number,
        backend=backend,
        steps=steps,
        schedule=schedule,
        hangup_after=float(call.get("hangup_after", 3)),
    )
    # Only resolve secrets for the backend actually in use.
    if backend == "twilio":
        job.twilio = _resolve_secrets(data.get("twilio", {}))
    elif backend == "sip":
        job.sip = _resolve_secrets(data.get("sip", {}))
    return job


def load(path: str | Path, backend_override: str | None = None) -> Job:
    with open(path, "rb") as f:
        return parse(tomllib.load(f), backend_override)
