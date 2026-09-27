"""Place the call through Twilio's REST API (stdlib only, no SDK needed).

Tip: verify your MagicJack number as a Twilio caller ID and use it as
`from_number`, so the reservation line sees the call coming from your
MagicJack number.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import ConfigError, Job
from ..dtmf import twiml
from .base import AttemptResult, log

API = "https://api.twilio.com/2010-04-01"
FINAL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}


class TwilioBackend:
    def __init__(self, cfg: dict, poll_interval: float = 2.0):
        for key in ("account_sid", "auth_token", "from_number"):
            if not cfg.get(key):
                raise ConfigError(f"twilio.{key} (or twilio.{key}_env) is required")
        self.sid = cfg["account_sid"]
        self.from_number = cfg["from_number"]
        self.record = bool(cfg.get("record", False))
        self.ring_timeout = int(cfg.get("ring_timeout", 30))
        self.poll_interval = poll_interval
        token = f"{self.sid}:{cfg['auth_token']}".encode()
        self._auth = "Basic " + base64.b64encode(token).decode()

    def _request(self, method: str, path: str, form: dict | None = None) -> dict:
        body = urllib.parse.urlencode(form).encode() if form else None
        req = urllib.request.Request(f"{API}/Accounts/{self.sid}/{path}", data=body, method=method)
        req.add_header("Authorization", self._auth)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Twilio {e.code}: {e.read().decode(errors='replace')}") from None

    def place(self, job: Job) -> AttemptResult:
        form = {
            "To": job.number,
            "From": self.from_number,
            "Twiml": twiml(job),
            "Timeout": str(self.ring_timeout),
        }
        if self.record:
            form["Record"] = "true"
        try:
            call = self._request("POST", "Calls.json", form)
        except (RuntimeError, OSError) as e:
            return AttemptResult(False, f"could not start call: {e}")
        call_sid = call["sid"]
        log.info("Twilio call %s created, status=%s", call_sid, call.get("status"))

        # Ring time + script + margin; the call can't legitimately outlast this.
        deadline = time.monotonic() + self.ring_timeout + job.script_duration + 60
        status = call.get("status")
        while status not in FINAL_STATUSES:
            if time.monotonic() > deadline:
                try:
                    self._request("POST", f"Calls/{call_sid}.json", {"Status": "completed"})
                except (RuntimeError, OSError) as e:
                    log.warning("could not hang up call %s: %s", call_sid, e)
                return AttemptResult(False, f"call {call_sid} did not finish in time; hung up")
            time.sleep(self.poll_interval)
            try:
                call = self._request("GET", f"Calls/{call_sid}.json")
            except (RuntimeError, OSError) as e:
                log.warning("status poll failed (%s); retrying", e)
                continue
            if call.get("status") != status:
                status = call.get("status")
                log.info("call %s -> %s", call_sid, status)

        if status != "completed":
            return AttemptResult(False, f"call ended with status {status!r}")
        duration = int(call.get("duration") or 0)
        # Pauses are whole seconds on Twilio's side, so allow a little slack.
        needed = job.script_duration - job.hangup_after - 1
        if duration < needed:
            return AttemptResult(
                False, f"far end hung up after {duration}s, before all digits were sent (~{needed:.0f}s needed)"
            )
        return AttemptResult(True, f"call {call_sid} completed ({duration}s)")
