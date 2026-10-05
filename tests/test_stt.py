"""Spoken answers (STT): the transcription gateway and the voice module's `transcribe`.

`httpx.MockTransport` plays OpenRouter's `/audio/transcriptions`, a temp folder stands in for `data/`, and
an in-memory SQLite database holds the app's tables, so nothing here touches the network or real data.
"""

import base64
import json

import httpx
import pytest
from sqlmodel import select

from interview_app.config import Settings, STTSettings
from interview_app.db import Application, InterviewSession, LLMCall, User, session_scope
from interview_app.interview.persona import Channel, SessionConfig
from interview_app.llm.calllog import make_db_recorder
from interview_app.llm.client import LLMClient, LLMError
from interview_app.voice import (
    STT_BUDGET_NOTICE,
    STT_EMPTY_NOTICE,
    STT_FAILED_NOTICE,
    TranscriptStatus,
    pcm_to_wav,
    transcribe,
)

STT_MODEL = "openai/whisper-large-v3-turbo"
RATE = 16000


def wav_of(seconds: float) -> bytes:
    """A silent 16 kHz mono WAV of the given length, like the browser's recorder produces."""
    return pcm_to_wav(b"\x00\x00" * int(RATE * seconds), rate=RATE)


class FakeSTT:
    """Plays `/audio/transcriptions`: queued replies (a dict body, an int status or an exception)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, int):
            return httpx.Response(reply, json={"error": {"message": "Model blocked by guardrail"}})
        return httpx.Response(200, json=reply)

    def body(self, n: int = 0) -> dict:
        return json.loads(self.requests[n].content)


def ok_reply(text: str = "I led the data engine.", cost: float = 0.00011) -> dict:
    return {"text": text, "usage": {"cost": cost, "seconds": 4}}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, openrouter_api_key="test", data_dir=tmp_path, max_retries=1)


def client_with(settings, fake, records=None) -> LLMClient:
    recorder = records.append if records is not None else None
    client = LLMClient(
        settings, recorder=recorder, sdk=object(), http=httpx.Client(transport=httpx.MockTransport(fake))
    )
    client.backoff_base_s = 0  # no real sleeping in tests
    return client


# --- LLMClient.transcribe --------------------------------------------------------------------------


def test_transcribe_sends_base64_wav_and_records_the_reported_cost(settings):
    fake, records = FakeSTT([ok_reply()]), []
    audio = wav_of(1)

    result = client_with(settings, fake, records).transcribe("stt", audio, model=STT_MODEL, language="en")

    assert result.text == "I led the data engine."
    [request] = fake.requests
    assert str(request.url) == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer test"
    body = fake.body()
    # Not the OpenAI multipart shape: JSON with plain base64 (no `data:` prefix) under input_audio.
    assert body == {
        "model": STT_MODEL,
        "input_audio": {"data": base64.b64encode(audio).decode("ascii"), "format": "wav"},
        "language": "en",
    }
    [rec] = records
    assert (rec.role, rec.model, rec.cost_usd, rec.ok) == ("stt", STT_MODEL, 0.00011, True)
    assert rec.latency_s >= 0


def test_transcribe_retries_a_server_error_then_succeeds(settings):
    fake, records = FakeSTT([503, ok_reply()]), []
    result = client_with(settings, fake, records).transcribe("stt", wav_of(1), model=STT_MODEL, language="en")
    assert result.text and len(fake.requests) == 2 and len(records) == 1


@pytest.mark.parametrize(
    "replies",
    [
        [404],  # blocked by the guardrail: not retried
        [503, 503],  # still failing after the retry
        [httpx.ConnectError("down"), httpx.ConnectError("down")],
        [{"usage": {"cost": 0.0001}}],  # 200 but no text field
    ],
)
def test_transcribe_errors_are_recorded_and_raised(settings, replies):
    fake, records = FakeSTT(replies), []
    with pytest.raises(LLMError):
        client_with(settings, fake, records).transcribe("stt", wav_of(1), model=STT_MODEL, language="en")
    assert len(records) == 1 and records[0].ok is False and records[0].role == "stt"
    if replies == [404]:
        assert len(fake.requests) == 1


def test_transcribe_failure_log_never_holds_the_key(settings, caplog):
    fake = FakeSTT([404])
    with pytest.raises(LLMError):
        client_with(settings, fake).transcribe("stt", wav_of(1), model=STT_MODEL, language="en")
    assert "Bearer" not in caplog.text and "test" not in caplog.text.replace("tests", "")


# --- voice.transcribe ------------------------------------------------------------------------------


def make_session(engine, channel: Channel = Channel.VOICE) -> tuple[int, int]:
    with session_scope(engine) as s:
        user = User(username="noor", password_hash="h", totp_secret_enc="e")
        s.add(user)
        s.flush()
        app = Application(user_id=user.id, company="Fjordlight Analytics", role="ML Engineer")
        s.add(app)
        s.flush()
        row = InterviewSession(
            user_id=user.id,
            application_id=app.id,
            company=app.company,
            role=app.role,
            config_json=SessionConfig(channel=channel).model_dump_json(),
            documents_json="{}",
            status="active",
        )
        s.add(row)
        s.flush()
        return user.id, row.id


def factory(engine, settings, fake):
    def make_llm(uid: int, session_id: int | None) -> LLMClient:
        client = LLMClient(
            settings,
            recorder=make_db_recorder(engine, uid, session_id),
            sdk=object(),
            http=httpx.Client(transport=httpx.MockTransport(fake)),
        )
        client.backoff_base_s = 0
        return client

    return make_llm


def calls(engine) -> list[LLMCall]:
    with session_scope(engine) as s:
        return list(s.exec(select(LLMCall)).all())


def files_under(path) -> list:
    return [p for p in path.rglob("*") if p.is_file() and p.suffix != ".db"]


def test_transcribe_returns_the_text_and_records_an_stt_call(engine, settings):
    uid, sid = make_session(engine)
    fake = FakeSTT([ok_reply("  I led the data engine.  ")])

    outcome = transcribe(engine, settings, factory(engine, settings, fake), uid, sid, wav_of(2))

    assert outcome.status == TranscriptStatus.OK and outcome.text == "I led the data engine."
    assert outcome.notice is None
    assert fake.body()["model"] == settings.stt.model and fake.body()["language"] == settings.stt.language
    [call] = calls(engine)
    assert (call.role, call.user_id, call.session_id, call.cost_usd, call.ok) == (
        "stt",
        uid,
        sid,
        0.00011,
        True,
    )
    assert files_under(settings.data_dir) == []  # the recording is never written to disk


def test_an_empty_transcript_means_nothing_was_heard(engine, settings):
    uid, sid = make_session(engine)
    outcome = transcribe(
        engine, settings, factory(engine, settings, FakeSTT([ok_reply("  ")])), uid, sid, wav_of(1)
    )
    assert outcome.status == TranscriptStatus.EMPTY and outcome.notice == STT_EMPTY_NOTICE
    assert outcome.text is None


def test_a_too_long_recording_is_refused_before_any_call(engine, settings):
    settings = settings.model_copy(update={"stt": STTSettings(max_seconds=2)})
    uid, sid = make_session(engine)
    fake = FakeSTT([])
    outcome = transcribe(engine, settings, factory(engine, settings, fake), uid, sid, wav_of(3))
    assert outcome.status == TranscriptStatus.TOO_LONG and "2 seconds" in outcome.notice
    assert fake.requests == [] and calls(engine) == []


def test_a_too_big_recording_is_refused_before_any_call(engine, settings):
    settings = settings.model_copy(update={"stt": STTSettings(max_bytes=1000)})
    uid, sid = make_session(engine)
    fake = FakeSTT([])
    outcome = transcribe(engine, settings, factory(engine, settings, fake), uid, sid, wav_of(1))
    assert outcome.status == TranscriptStatus.TOO_LONG and fake.requests == []


def test_a_recording_that_is_not_wav_is_a_failure_not_a_crash(engine, settings):
    uid, sid = make_session(engine)
    fake = FakeSTT([])
    outcome = transcribe(engine, settings, factory(engine, settings, fake), uid, sid, b"not audio")
    assert outcome.status == TranscriptStatus.FAILED and fake.requests == []


def test_transcription_stops_when_the_budget_is_used_up(engine, settings):
    uid, sid = make_session(engine)
    with session_scope(engine) as s:
        s.add(LLMCall(user_id=uid, session_id=sid, role="interviewer", model="m", cost_usd=1.0))
    fake = FakeSTT([])
    outcome = transcribe(engine, settings, factory(engine, settings, fake), uid, sid, wav_of(1))
    assert outcome.status == TranscriptStatus.BUDGET and outcome.notice == STT_BUDGET_NOTICE
    assert "type" in outcome.notice  # typing still works
    assert fake.requests == []


def test_a_model_failure_returns_a_notice(engine, settings, caplog):
    uid, sid = make_session(engine)
    outcome = transcribe(engine, settings, factory(engine, settings, FakeSTT([404])), uid, sid, wav_of(1))
    assert outcome.status == TranscriptStatus.FAILED and outcome.notice == STT_FAILED_NOTICE
    [call] = calls(engine)
    assert call.role == "stt" and call.ok is False


def test_the_transcript_is_never_logged(engine, settings, caplog):
    caplog.set_level("DEBUG")
    uid, sid = make_session(engine)
    secret = "My salary at Fjordlight was ninety thousand."
    transcribe(engine, settings, factory(engine, settings, FakeSTT([ok_reply(secret)])), uid, sid, wav_of(1))
    assert "ninety thousand" not in caplog.text


def test_another_users_or_a_text_session_is_not_transcribed(engine, settings):
    uid, sid = make_session(engine)
    fake = FakeSTT([])
    other = transcribe(engine, settings, factory(engine, settings, fake), uid + 1, sid, wav_of(1))
    assert other.status == TranscriptStatus.FAILED
    with session_scope(engine) as s:
        row = s.get(InterviewSession, sid)
        row.config_json = SessionConfig(channel=Channel.TEXT).model_dump_json()
        s.add(row)
    text = transcribe(engine, settings, factory(engine, settings, fake), uid, sid, wav_of(1))
    assert text.status == TranscriptStatus.TEXT_SESSION
    assert fake.requests == []
