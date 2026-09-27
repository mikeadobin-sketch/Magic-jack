from __future__ import annotations

from ..config import Job
from .base import AttemptResult, Backend


def get_backend(job: Job) -> Backend:
    if job.backend == "twilio":
        from .twilio import TwilioBackend
        return TwilioBackend(job.twilio)
    if job.backend == "sip":
        from .sip import SipBackend
        return SipBackend(job.sip)
    from .dryrun import DryRunBackend
    return DryRunBackend()


__all__ = ["AttemptResult", "Backend", "get_backend"]
