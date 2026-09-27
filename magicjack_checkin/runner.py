"""Wait for the check-in window, then place the call, retrying until it works."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from .backends import Backend
from .backends.base import log
from .config import Job

Clock = Callable[[], datetime]


def run(job: Job, backend: Backend, *, now: Clock | None = None,
        sleep: Callable[[float], None] = time.sleep, ignore_schedule: bool = False) -> bool:
    sched = job.schedule
    now = now or (lambda: datetime.now(sched.tz))

    if not ignore_schedule and sched.start:
        delay = (sched.start - now()).total_seconds()
        if delay > 0:
            log.info("waiting %.0fs until window opens at %s", delay, sched.start.isoformat())
            _sleep_until(sched.start, now, sleep)

    for attempt in range(1, sched.max_attempts + 1):
        if not ignore_schedule and sched.end and now() >= sched.end:
            log.error("check-in window closed at %s; giving up", sched.end.isoformat())
            return False
        log.info("attempt %d/%d: calling %s", attempt, sched.max_attempts, job.number)
        result = backend.place(job)
        if result.success:
            log.info("check-in succeeded: %s", result.detail)
            return True
        log.warning("attempt %d failed: %s", attempt, result.detail)
        if attempt == sched.max_attempts:
            break
        if (not ignore_schedule and sched.end
                and (sched.end - now()).total_seconds() < sched.retry_interval):
            log.error("not enough time left in the window to retry")
            return False
        log.info("retrying in %.0fs", sched.retry_interval)
        sleep(sched.retry_interval)

    log.error("all %d attempts failed", sched.max_attempts)
    return False


def _sleep_until(target: datetime, now: Clock, sleep: Callable[[float], None]) -> None:
    # Sleep in chunks so clock changes (laptop sleep, NTP) don't make us late.
    while (remaining := (target - now()).total_seconds()) > 0:
        sleep(min(remaining, 30))
