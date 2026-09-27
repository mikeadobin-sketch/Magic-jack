from __future__ import annotations

from ..config import Job
from ..dtmf import twiml
from .base import AttemptResult, log


class DryRunBackend:
    """Prints what would happen on the call without dialing anything."""

    def place(self, job: Job) -> AttemptResult:
        log.info("[dry-run] dialing %s", job.number)
        t = 0.0
        for i, step in enumerate(job.steps, 1):
            t += step.wait
            log.info("[dry-run] t=%5.1fs  step %d: key in %s (%.2fs between digits)",
                     t, i, step.digits, step.digit_gap)
            t += max(len(step.digits) - 1, 0) * step.digit_gap
        log.info("[dry-run] t=%5.1fs  hang up", t + job.hangup_after)
        log.info("[dry-run] equivalent TwiML: %s", twiml(job))
        return AttemptResult(True, "dry run")
