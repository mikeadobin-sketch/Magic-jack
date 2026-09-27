from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from ..config import Job

log = logging.getLogger("magicjack_checkin")


@dataclass
class AttemptResult:
    success: bool
    detail: str


class Backend(Protocol):
    def place(self, job: Job) -> AttemptResult:
        """Dial job.number, play the steps, hang up, and report whether it worked."""
