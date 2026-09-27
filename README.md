# magicjack-checkin

Automatically call a reservation line and key in digits (touch-tones) with
precise timing, inside a check-in window, retrying if the call fails.

## Important: MagicJack has no public API

MagicJack doesn't offer a developer API for placing calls or sending
touch-tones, so this app can't "log into" MagicJack. It places calls through
a pluggable **backend** instead:

| Backend   | What it uses | Notes |
|-----------|--------------|-------|
| `twilio`  | Twilio Voice REST API | Most reliable. Verify your MagicJack number as a Twilio **caller ID** and the call shows up as coming from your MagicJack number. Costs about a cent per minute. |
| `sip`     | Any SIP account, via `pyVoIP` | Dials directly and sends DTMF as in-band tones. MagicJack doesn't officially give out SIP credentials, so use this with a SIP provider you have credentials for. |
| `dry-run` | Nothing | Prints the call timeline and the generated TwiML. Good for checking your timing. |

## Install

```bash
python3 -m pip install -e .          # Twilio + dry-run need nothing else (Python 3.11+)
python3 -m pip install -e '.[sip]'   # add the SIP backend
```

## Use

1. Copy `config.example.toml` to e.g. `my-reservation.toml` and fill in:
   - `call.number`: the reservation line.
   - `[schedule]`: when the check-in window opens and closes, plus the retry policy.
   - `[[steps]]`: each step waits `wait` seconds, then keys in `digits`
     with `digit_gap` seconds between digits.
2. Put credentials in environment variables (keys ending in `_env` name them):
   ```bash
   export TWILIO_ACCOUNT_SID=ACxxxxxxxx TWILIO_AUTH_TOKEN=xxxxxxxx
   ```
3. Preview, then run:
   ```bash
   magicjack-checkin my-reservation.toml --dry-run --now   # preview the timing
   magicjack-checkin my-reservation.toml                   # wait for the window, then call
   magicjack-checkin my-reservation.toml --now             # call right away
   ```

The process sleeps until `schedule.start`, calls, and retries every
`retry_interval` seconds, up to `max_attempts` times, until the call succeeds
or `schedule.end` passes. The exit code is `0` on success and `1` on failure.
To run it unattended, start it in `tmux`/`screen` ahead of time, or use
cron or a systemd timer.

**Finding the right timing:** call the line once by hand with a stopwatch.
Note how long each prompt takes before it accepts input, and set each
`wait` to a second or so past that. Set `twilio.record = true` for the
first real run so you can listen to the recording in the Twilio console
and confirm the check-in went through.

### What counts as success

- **Twilio:** the call was answered, and the far end stayed on long enough
  for every digit to be sent.
- **SIP:** the call was answered and every digit was sent before the far
  end hung up.

Neither backend can understand the voice prompt that says "you're checked
in", so use `record = true` if you need proof.

## Development

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest
```
