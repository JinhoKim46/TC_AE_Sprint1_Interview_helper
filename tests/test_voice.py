"""Voice channel (TTS): the speech gateway, the WAV wrapper and the voice module.

A fake SDK stands in for OpenRouter's `/audio/speech`, a temp folder for `data/`, and an in-memory SQLite
database for the app's tables, so nothing here touches the network or the real data folder.
"""

import io
import wave
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlmodel import select

from interview_app.applications import delete_application
from interview_app.config import Settings, TTSSettings
from interview_app.db import Application, InterviewSession, LLMCall, Turn, TurnAudio, User, session_scope
from interview_app.history import delete_session
from interview_app.interview.persona import Channel, InterviewType, SessionConfig
from interview_app.llm.calllog import make_db_recorder
from interview_app.llm.client import LLMClient, LLMError, pcm_format, pcm_seconds
from interview_app.llm.pricing import PriceCatalog
from interview_app.preferences import Preferences, to_session_config
from interview_app.voice import (
    BUDGET_NOTICE,
    FAILED_NOTICE,
    SpeechStatus,
    pcm_to_wav,
    session_voice,
    speak,
    stored_audio,
)

TTS_MODEL = "google/gemini-3.8-flash-lite-tts"
PCM_TYPE = "audio/pcm;rate=24000;channels=1"
ONE_SECOND = b"\x01\x00" * 24000  # 24 kHz, mono, 16-bit: 48,000 bytes per second


class FakeSpeechSDK:
    """Mimics `OpenAI().audio.speech.with_raw_response.create`: queued replies, recorded requests."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        raw = SimpleNamespace(create=self._create)
        self.audio = SimpleNamespace(speech=SimpleNamespace(with_raw_response=raw))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def raw_audio(audio: bytes = ONE_SECOND, content_type: str = PCM_TYPE):
    # httpx headers are case-insensitive; lower-case keys in a dict behave the same for `.get`.
    return SimpleNamespace(content=audio, headers={"content-type": content_type, "x-generation-id": "gen-1"})


def catalog(settings: Settings) -> PriceCatalog:
    entry = {"id": TTS_MODEL, "name": "TTS", "pricing": {"prompt": "0.0000005", "completion": "0.000006"}}
    return PriceCatalog(settings, fetch=lambda: {"data": [entry]})


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, openrouter_api_key="test", data_dir=tmp_path)


# --- WAV wrapper and PCM format ------------------------------------------------------------------


def test_pcm_to_wav_adds_a_44_byte_header_and_keeps_the_samples():
    pcm = ONE_SECOND
    wav = pcm_to_wav(pcm, rate=24000, channels=1)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert len(wav) == 44 + len(pcm)
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
        assert w.getnframes() == 24000
        assert w.readframes(w.getnframes()) == pcm


def test_pcm_format_and_duration_come_from_the_content_type():
    assert pcm_format(PCM_TYPE) == (24000, 1)
    assert pcm_format("audio/pcm") == (24000, 1)  # documented defaults
    assert pcm_format("audio/mpeg") is None
    assert pcm_seconds(ONE_SECOND, PCM_TYPE) == 1.0
    assert pcm_seconds(ONE_SECOND, "audio/pcm;rate=48000;channels=1") == 0.5
    assert pcm_seconds(ONE_SECOND, "audio/mpeg") == 0.0


# --- LLMClient.speech ------------------------------------------------------------------------------


def test_speech_records_a_tts_call_with_an_estimated_cost(settings):
    records = []
    sdk = FakeSpeechSDK([raw_audio()])
    client = LLMClient(settings, recorder=records.append, sdk=sdk, pricing=catalog(settings))
    text = "x" * 40  # 40 chars ~ 10 input tokens

    result = client.speech("tts", text, model=TTS_MODEL, voice="Kore")

    assert result.audio == ONE_SECOND and result.content_type == PCM_TYPE
    assert result.generation_id == "gen-1"
    assert sdk.requests == [{"model": TTS_MODEL, "input": text, "voice": "Kore", "response_format": "pcm"}]
    rec = records[0]
    # 1 s of audio x 32 audio tokens per second (TTSSettings.audio_tokens_per_second)
    assert (rec.role, rec.model, rec.prompt_tokens, rec.completion_tokens, rec.ok) == (
        "tts",
        TTS_MODEL,
        10,
        32,
        True,
    )
    assert rec.cost_usd == pytest.approx(10 * 0.0000005 + 32 * 0.000006)


def test_speech_error_is_recorded_and_raised(settings):
    records = []
    client = LLMClient(settings, recorder=records.append, sdk=FakeSpeechSDK([RuntimeError("404 guardrail")]))
    with pytest.raises(LLMError):
        client.speech("tts", "Hello.", model=TTS_MODEL, voice="Kore")
    assert records[0].ok is False and "guardrail" in records[0].error


def test_speech_without_a_price_catalog_costs_zero(settings):
    records = []
    client = LLMClient(settings, recorder=records.append, sdk=FakeSpeechSDK([raw_audio()]))
    client.speech("tts", "Hello.", model=TTS_MODEL, voice="Kore")
    assert records[0].cost_usd == 0.0


# --- Voice selection -------------------------------------------------------------------------------


def test_each_persona_has_a_voice_and_the_preference_overrides_it(settings):
    tts = settings.tts
    config = to_session_config(Preferences(channel=Channel.VOICE), tts=tts)
    assert config.voice == tts.voice_for(config.interview_type.value)

    picked = to_session_config(Preferences(channel=Channel.VOICE, voice="Puck"), tts=tts)
    assert picked.voice == "Puck"

    # An unknown saved voice (removed from config later) falls back to the persona's.
    stale = to_session_config(Preferences(channel=Channel.VOICE, voice="Nobody"), tts=tts)
    assert stale.voice == tts.voice_for(stale.interview_type.value)

    text = to_session_config(Preferences(channel=Channel.TEXT, voice="Puck"), tts=tts)
    assert text.voice is None


def test_session_voice_uses_the_stored_voice_else_the_persona(settings):
    assert session_voice(SessionConfig(channel=Channel.VOICE, voice="Puck"), settings) == "Puck"
    legacy = SessionConfig(channel=Channel.VOICE, interview_type=InterviewType.BEHAVIORAL)
    assert session_voice(legacy, settings) == settings.tts.voices["behavioral"]


def test_unknown_voice_in_config_is_rejected():
    with pytest.raises(ValidationError):
        TTSSettings(voices={"behavioral": "NotAVoice"})


# --- The voice module ------------------------------------------------------------------------------


def make_session(
    engine, channel: Channel = Channel.VOICE, voice: str | None = "Kore"
) -> tuple[int, int, int]:
    """A user, an application and a session with an opening question (idx 0) and an answer (idx 1)."""
    with session_scope(engine) as s:
        user = User(username="noor", password_hash="h", totp_secret_enc="e")
        s.add(user)
        s.flush()
        app = Application(user_id=user.id, company="Fjordlight Analytics", role="ML Engineer")
        s.add(app)
        s.flush()
        config = SessionConfig(channel=channel, voice=voice if channel == Channel.VOICE else None)
        row = InterviewSession(
            user_id=user.id,
            application_id=app.id,
            company=app.company,
            role=app.role,
            config_json=config.model_dump_json(),
            documents_json="{}",
            status="active",
        )
        s.add(row)
        s.flush()
        s.add(
            Turn(session_id=row.id, user_id=user.id, idx=0, speaker="interviewer", text="Tell me about you.")
        )
        s.add(Turn(session_id=row.id, user_id=user.id, idx=1, speaker="candidate", text="I build models."))
        return user.id, app.id, row.id


def factory(engine, settings, sdk):
    def make_llm(uid: int, session_id: int | None) -> LLMClient:
        return LLMClient(
            settings, recorder=make_db_recorder(engine, uid, session_id), sdk=sdk, pricing=catalog(settings)
        )

    return make_llm


def calls(engine) -> list[LLMCall]:
    with session_scope(engine) as s:
        return list(s.exec(select(LLMCall)).all())


def test_speak_generates_once_and_reuses_the_stored_file(engine, settings):
    uid, _, sid = make_session(engine)
    sdk = FakeSpeechSDK([raw_audio()])
    make_llm = factory(engine, settings, sdk)

    first = speak(engine, settings, make_llm, uid, sid, 0)
    second = speak(engine, settings, make_llm, uid, sid, 0)

    assert first.status == SpeechStatus.GENERATED and second.status == SpeechStatus.READY
    assert first.path == second.path == settings.data_dir / "audio" / str(uid) / str(sid) / "0.wav"
    assert len(sdk.requests) == 1  # the replay cost nothing
    assert sdk.requests[0]["voice"] == "Kore"  # the session's stored voice
    assert sdk.requests[0]["input"] == "Tell me about you."
    with wave.open(str(first.path)) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 24000
    assert stored_audio(engine, settings, uid, sid, 0) == first.path
    with session_scope(engine) as s:
        row = s.exec(select(TurnAudio)).one()
    assert (row.user_id, row.session_id, row.turn_idx, row.voice, row.model) == (
        uid,
        sid,
        0,
        "Kore",
        TTS_MODEL,
    )
    assert row.path == f"audio/{uid}/{sid}/0.wav"  # relative to data_dir
    [call] = calls(engine)
    assert (call.role, call.session_id, call.user_id, call.ok) == ("tts", sid, uid, True)
    assert call.cost_usd > 0  # counts in the session's cost and budget


def test_speak_does_nothing_in_a_text_session(engine, settings):
    uid, _, sid = make_session(engine, channel=Channel.TEXT)
    sdk = FakeSpeechSDK([])
    outcome = speak(engine, settings, factory(engine, settings, sdk), uid, sid, 0)
    assert outcome.status == SpeechStatus.TEXT_SESSION and outcome.path is None
    assert sdk.requests == []


def test_speak_only_speaks_interviewer_turns(engine, settings):
    uid, _, sid = make_session(engine)
    sdk = FakeSpeechSDK([])
    outcome = speak(engine, settings, factory(engine, settings, sdk), uid, sid, 1)  # the candidate's answer
    assert outcome.status == SpeechStatus.FAILED and sdk.requests == []


def test_speak_is_skipped_when_the_budget_is_used_up(engine, settings):
    uid, _, sid = make_session(engine)
    with session_scope(engine) as s:
        s.add(LLMCall(user_id=uid, session_id=sid, role="interviewer", model="m", cost_usd=1.0))
    sdk = FakeSpeechSDK([])
    outcome = speak(engine, settings, factory(engine, settings, sdk), uid, sid, 0)
    assert outcome.status == SpeechStatus.BUDGET and outcome.notice == BUDGET_NOTICE
    assert sdk.requests == []


def test_a_tts_failure_returns_a_notice_and_no_audio(engine, settings):
    uid, _, sid = make_session(engine)
    sdk = FakeSpeechSDK([RuntimeError("503")])
    outcome = speak(engine, settings, factory(engine, settings, sdk), uid, sid, 0)
    assert outcome.status == SpeechStatus.FAILED and outcome.notice == FAILED_NOTICE
    assert outcome.path is None and stored_audio(engine, settings, uid, sid, 0) is None
    [call] = calls(engine)
    assert call.role == "tts" and call.ok is False


def test_an_unexpected_audio_format_is_a_failure_not_a_crash(engine, settings):
    uid, _, sid = make_session(engine)
    sdk = FakeSpeechSDK([raw_audio(b"ID3...", content_type="audio/mpeg")])
    outcome = speak(engine, settings, factory(engine, settings, sdk), uid, sid, 0)
    assert outcome.status == SpeechStatus.FAILED


def test_another_users_session_is_not_spoken(engine, settings):
    uid, _, sid = make_session(engine)
    sdk = FakeSpeechSDK([])
    outcome = speak(engine, settings, factory(engine, settings, sdk), uid + 1, sid, 0)
    assert outcome.status == SpeechStatus.FAILED and sdk.requests == []


def test_deleting_the_session_removes_its_audio_files_and_rows(engine, settings):
    uid, _, sid = make_session(engine)
    outcome = speak(engine, settings, factory(engine, settings, FakeSpeechSDK([raw_audio()])), uid, sid, 0)
    assert outcome.path.is_file()

    assert delete_session(engine, uid, sid, settings=settings)

    assert not outcome.path.exists() and not outcome.path.parent.exists()
    with session_scope(engine) as s:
        assert s.exec(select(TurnAudio)).all() == []


def test_deleting_the_application_removes_its_audio_files_and_rows(engine, settings):
    uid, app_id, sid = make_session(engine)
    outcome = speak(engine, settings, factory(engine, settings, FakeSpeechSDK([raw_audio()])), uid, sid, 0)

    assert delete_application(engine, uid, app_id, settings=settings)

    assert not outcome.path.parent.exists()
    with session_scope(engine) as s:
        assert s.exec(select(TurnAudio)).all() == []
