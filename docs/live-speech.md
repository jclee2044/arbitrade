# Discuss one saved decision by voice

In the dashboard, scroll to **Discuss a recorded decision by voice**, choose a
saved decision and inspect its symbol, cutoff, analyst/reviewer/validation and
recorded paper outcome. Click **Start voice** and allow microphone access. Ask a
question, listen, then ask a follow-up without starting another session. Incoming
audio plays in the panel; use its Play control if autoplay is blocked. Provider
transcript fragments appear separately for You and Assistant.

**The microphone and speakers belong to the computer running the browser.**
A Mac can use its own audio while the code/backend remain on Omarchy. Use the
existing SSH tunnel and open `http://127.0.0.1:5173` in Safari or Chrome on the
Mac. The tunnel carries dashboard/API signaling; WebRTC audio travels directly
between that browser and OpenAI. No SSH audio forwarding or Omarchy microphone
configuration is required. An in-app browser may require additional microphone
permission; a regular Mac browser is an alternative. Use localhost or HTTPS.

Click **End voice** to stop microphone tracks immediately. It sends session.close
when connected, waits for session.closed and closes the peer/audio output, with a
15second cleanup deadline. Startup failure, microphone denial, network disconnect,
decision change or panel removal closes local media/connection resources. Ending
while the permission prompt is pending also stops any tracks granted afterward.
The explicit Microphone active/off indicator reflects local capture, independently
of the connection status.

## Read-only session context

The backend reads one consistent SQLite transaction using mode=ro. It loads the
saved snapshot/hash, symbol/interval/cutoff, indicator values, analyst's actual
proposal/named answers, reviewer verdict, Python validation and any linked
application/order/fill/P&L. It also supplies current recorded balances as of the
summary read time, separately from frozen and fill-time balances.

The voice session can discuss only that frozen summary. Missing review, missing
fill or missing account data remain missing; a proposal/pending order is not
reported as an executed trade. Later activity is not streamed into the session:
End and start again to refresh the record. Voice has no trading, automation,
lookup or analysis tools and no route to execute an order. Instructions require
it to identify evidence that the record does not contain. It cannot modify SQLite.

The browser requests audio, adds microphone tracks to RTCPeerConnection, creates
the oai-events data channel before its offer, sets local description and waits
for ICE gathering. It posts the SDP and decision ID to FastAPI. Python sends
server-owned `session` and WebRTC `transport` JSON to OpenAI's
`POST /v1/live/sessions` using the backend key. Model gpt-live-1/voice marin,
store=false and the selected record are configured only on the server. The
browser applies the answer and waits for session.started. It never sends
session.start, a key or client-supplied session instructions.

WebRTC carries both audio directions. The data channel handles lifecycle and
input/output transcript deltas, preserving fragment text/spaces and timing.
Captions are grouped by speaker and are not a claim of finalized conversational
turn boundaries. Application code does not persist microphone recordings or
transcripts. Provider storage is disabled in session configuration. Verification
artifacts explicitly described below are separate test records.

## API and checks

- `GET /api/voice/decisions`: latest50 saved decisions with snapshots.
- `GET /api/voice/decisions/{id}`: read-only summary for inspection.
- `POST /api/voice/sessions`: decision_id and audio SDP offer; returns provider
  session ID, WebRTC answer, frozen summary and provider mode. Extra configuration
  fields are rejected. No database write and no automatic retry.

The existing private backend/.env key is reused. No SDK or new dependency was
installed. Provider failures use sanitized codes, with no raw body/key logging.
The backend HTTP request has a20second timeout, browser ICE10seconds and startup
35seconds after microphone acquisition. The app remains loopback-bound.

```bash
PYTHONPATH=backend/.packages /usr/bin/python -m unittest backend.test_voice -v
PYTHONPATH=backend/.packages /usr/bin/python -m scripts.voice_smoke --output /tmp/arbitrade-voice-results
```

The repeatable SmokeTest starts isolated services and actual browser WebRTC peers
with synthetic microphone/tone tracks. The provider negotiation and captions are
**mocked**. It verifies media in both directions, two questions in one session,
selected SQL context, native track/peer cleanup on End, denied access, failed
provider, disconnect and late permission. Every SQLite table remains unchanged.
It cleans up its services/browser/disposable databases and makes no live call.

Separately, one actual OpenAI WebRTC session using a synthetic microphone and
application text cues returned real audio and captions matching the selected
wait decision: analyst wait/reviewer accept/valid;1000cash/zero shares/no recorded
trade. End released tracks/peer. This verifies live negotiation/output, **not a
human microphone/speaker conversation**. Captured provider output and captions
are in screenshots/voice-live-provider-2026-11-11. The physical Mac check remains
pending until the student reports what was heard and microphone release.

For that hardware check, select valid wait decision ending3332c9, Start voice,
ask “What did the agents decide for this symbol?” then “What happened to the
paper account?”, listen, End voice and confirm **Microphone: off**. Expected
record: AAPL, analyst wait, reviewer accept, valid; no linked trade, cash1000 and
zero shares. Compare the spoken answer with the on-screen summary, not a new
market quote. See [verification.md](verification.md) for actual observations.

Official sources:
[GPT-Live WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc?voice-api=live),
[session creation](https://developers.openai.com/api/reference/resources/live/methods/create),
[session lifecycle/transcripts](https://developers.openai.com/api/docs/guides/live-conversations).
