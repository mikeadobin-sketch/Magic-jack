"""Place the call directly over SIP, sending DTMF as in-band tones.

Requires `pip install pyVoIP`. MagicJack does not officially hand out SIP
credentials, so this works with any SIP account/provider you do have
credentials for (including a MagicJack line if you've obtained them).
"""

from __future__ import annotations

import socket
import time

from ..config import ConfigError, Job
from ..dtmf import silence, tone
from .base import AttemptResult, log

TONE_SECONDS = 0.15


def _local_ip(server: str, port: int) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((server, port))
        return s.getsockname()[0]


class SipBackend:
    def __init__(self, cfg: dict):
        for key in ("server", "username", "password"):
            if not cfg.get(key):
                raise ConfigError(f"sip.{key} (or sip.{key}_env) is required")
        self.cfg = cfg
        self.port = int(cfg.get("port", 5060))
        self.ring_timeout = float(cfg.get("ring_timeout", 30))

    def place(self, job: Job) -> AttemptResult:
        try:
            from pyVoIP.VoIP import CallState, VoIPPhone
        except ImportError:
            return AttemptResult(False, "the SIP backend needs pyVoIP: pip install pyVoIP")

        cfg = self.cfg
        phone = VoIPPhone(
            cfg["server"], self.port, cfg["username"], cfg["password"],
            myIP=cfg.get("local_ip") or _local_ip(cfg["server"], self.port),
            sipPort=int(cfg.get("local_port", 5060)),
        )
        phone.start()
        call = None
        try:
            call = phone.call(job.number)
            deadline = time.monotonic() + self.ring_timeout
            while call.state not in (CallState.ANSWERED, CallState.ENDED):
                if time.monotonic() > deadline:
                    return AttemptResult(False, "no answer")
                time.sleep(0.1)
            if call.state == CallState.ENDED:
                return AttemptResult(False, "call rejected or busy")
            log.info("answered")

            for i, step in enumerate(job.steps, 1):
                if not self._sleep_while_up(call, CallState, step.wait):
                    return AttemptResult(False, f"far end hung up before step {i}")
                log.info("step %d: keying %s", i, step.digits)
                for j, digit in enumerate(step.digits):
                    gap = step.digit_gap if j < len(step.digits) - 1 else 0
                    call.write_audio(tone(digit, TONE_SECONDS) + silence(gap))
                    if not self._sleep_while_up(call, CallState, TONE_SECONDS + gap):
                        return AttemptResult(False, f"far end hung up during step {i}")
            self._sleep_while_up(call, CallState, job.hangup_after)
            return AttemptResult(True, "all digits sent")
        finally:
            if call is not None and call.state == CallState.ANSWERED:
                try:
                    call.hangup()
                except Exception:  # already gone
                    pass
            phone.stop()

    @staticmethod
    def _sleep_while_up(call, CallState, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if call.state != CallState.ANSWERED:
                return False
            time.sleep(min(0.05, max(end - time.monotonic(), 0)))
        return call.state == CallState.ANSWERED
