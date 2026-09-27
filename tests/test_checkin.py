from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from magicjack_checkin import cli
from magicjack_checkin.backends.base import AttemptResult
from magicjack_checkin.config import ConfigError, load, parse
from magicjack_checkin.dtmf import SAMPLE_RATE, tone, twiml
from magicjack_checkin.runner import run

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"


def job_data(**schedule):
    return {
        "call": {"number": "+18005551234", "backend": "dry-run"},
        "schedule": {"timezone": "UTC", **schedule},
        "steps": [{"wait": 6, "digits": "1"}, {"wait": 2.5, "digits": "12-34 #", "digit_gap": 0.5}],
    }


def test_parse_normalizes_digits_and_timezone():
    job = parse(job_data(start="2026-10-03T15:00:00"))
    assert job.steps[1].digits == "1234#"
    assert job.schedule.start.tzinfo == ZoneInfo("UTC")
    assert job.steps[1].duration == pytest.approx(2.5 + 4 * 0.5)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["call"].pop("number"), "call.number"),
    (lambda d: d.update(steps=[]), "steps"),
    (lambda d: d["steps"].append({"digits": "12a"}), "only 0-9"),
    (lambda d: d["call"].update(backend="pots"), "backend"),
    (lambda d: d["schedule"].update(start="2026-01-02T00:00", end="2026-01-01T00:00"), "after"),
])
def test_parse_rejects_bad_config(mutate, message):
    data = job_data()
    mutate(data)
    with pytest.raises(ConfigError, match=message):
        parse(data)


def test_secrets_come_from_env(monkeypatch):
    data = job_data()
    data["call"]["backend"] = "twilio"
    data["twilio"] = {"auth_token_env": "TEST_TOKEN", "account_sid": "AC1"}
    with pytest.raises(ConfigError, match="TEST_TOKEN"):
        parse(data)
    monkeypatch.setenv("TEST_TOKEN", "secret")
    assert parse(data).twilio == {"auth_token": "secret", "account_sid": "AC1"}


def test_twiml_timing():
    job = parse(job_data())
    assert twiml(job) == (
        '<Response><Pause length="6"/><Play digits="1"/>'
        '<Pause length="2"/><Play digits="w1w2w3w4w#"/>'
        '<Pause length="3"/><Hangup/></Response>'
    )


def test_tone_is_8bit_pcm_of_right_length():
    data = tone("5", 0.1)
    assert len(data) == int(SAMPLE_RATE * 0.1)
    assert min(data) < 100 and max(data) > 156


class FakeBackend:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def place(self, job):
        self.calls += 1
        return self.results.pop(0)


class FakeClock:
    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += timedelta(seconds=seconds)


T0 = datetime(2026, 10, 3, 14, 50, tzinfo=ZoneInfo("UTC"))


def test_waits_for_window_then_retries_until_success():
    job = parse(job_data(start="2026-10-03T15:00:00", retry_interval=60, max_attempts=3))
    clock = FakeClock(T0)
    backend = FakeBackend([AttemptResult(False, "busy"), AttemptResult(True, "ok")])
    assert run(job, backend, now=clock.now, sleep=clock.sleep)
    assert backend.calls == 2
    assert clock.t == datetime(2026, 10, 3, 15, 1, tzinfo=ZoneInfo("UTC"))


def test_gives_up_when_window_closes():
    job = parse(job_data(start="2026-10-03T15:00:00", end="2026-10-03T15:01:30",
                         retry_interval=60, max_attempts=10))
    clock = FakeClock(T0)
    backend = FakeBackend([AttemptResult(False, "busy")] * 10)
    assert not run(job, backend, now=clock.now, sleep=clock.sleep)
    assert backend.calls == 2


def test_example_config_loads(monkeypatch):
    for var in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"):
        monkeypatch.setenv(var, "x")
    job = load(EXAMPLE)
    assert job.backend == "twilio" and len(job.steps) == 3


def test_cli_dry_run(capsys):
    assert cli.main([str(EXAMPLE), "--dry-run", "--now"]) == 0


@pytest.mark.parametrize("final, ok", [
    ({"status": "completed", "duration": "18"}, True),
    ({"status": "completed", "duration": "4"}, False),  # hung up mid-script
    ({"status": "busy", "duration": "0"}, False),
])
def test_twilio_backend_judges_outcome(monkeypatch, final, ok):
    from magicjack_checkin.backends.twilio import TwilioBackend

    backend = TwilioBackend({"account_sid": "AC1", "auth_token": "t", "from_number": "+1"},
                            poll_interval=0)
    sent = []

    def fake_request(method, path, form=None):
        sent.append((method, path, form))
        if method == "POST":
            return {"sid": "CA1", "status": "queued"}
        return {"sid": "CA1", **final}

    monkeypatch.setattr(backend, "_request", fake_request)
    job = parse(job_data())
    assert backend.place(job).success is ok
    assert sent[0][2]["Twiml"] == twiml(job)
