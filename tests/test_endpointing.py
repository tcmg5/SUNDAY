"""Endpointing decides when you've stopped talking. Getting it wrong is the
difference between a usable assistant and one that interrupts you constantly."""
import numpy as np
import pytest

from jarvis.audio.vad import Endpointer
from jarvis.core.state import Bus, State


@pytest.fixture
def cfg():
    return {
        "audio": {
            "sample_rate": 16000,
            "block_size": 1280,
            "silence_timeout_sec": 1.0,
            "max_utterance_sec": 5.0,
            "min_utterance_sec": 0.3,
            "vad_aggressiveness": 2,
        }
    }


class FakeMic:
    """Replays a scripted audio timeline, then goes silent."""

    def __init__(self, blocks):
        self.blocks = list(blocks)

    def read(self, timeout=1.0):
        return self.blocks.pop(0) if self.blocks else None


def speech_block(n=1280):
    """Broadband noise - reads as speech to both the VAD and the RMS gate."""
    rng = np.random.default_rng(0)
    return (rng.normal(0, 4000, n)).astype(np.int16)


def silence_block(n=1280):
    return np.zeros(n, dtype=np.int16)


def test_stops_after_trailing_silence(cfg):
    ep = Endpointer(cfg)
    # 0.8s of speech, then 2s of silence - well past the 1.0s timeout.
    blocks = [speech_block() for _ in range(10)] + [silence_block() for _ in range(25)]
    mic = FakeMic(blocks)
    audio = ep.record(mic)
    assert len(audio) > 0
    # It must cut off during the silence, not consume all of it.
    assert len(audio) < sum(len(b) for b in blocks)


def test_returns_empty_when_nobody_speaks(cfg):
    ep = Endpointer(cfg)
    mic = FakeMic([silence_block() for _ in range(60)])
    assert len(ep.record(mic)) == 0


def test_brief_pause_does_not_end_the_utterance(cfg):
    """'Organize my downloads... uh... by date' must survive the hesitation."""
    ep = Endpointer(cfg)
    blocks = (
        [speech_block() for _ in range(8)]
        + [silence_block() for _ in range(6)]   # ~0.5s pause, under the timeout
        + [speech_block() for _ in range(8)]
        + [silence_block() for _ in range(20)]
    )
    mic = FakeMic(blocks)
    audio = ep.record(mic)
    # Both speech segments and the pause between them should be captured.
    assert len(audio) > 20 * 1280


def test_preroll_is_prepended(cfg):
    ep = Endpointer(cfg)
    preroll = speech_block(3200)
    mic = FakeMic([speech_block() for _ in range(6)] + [silence_block() for _ in range(20)])
    audio = ep.record(mic, preroll=preroll)
    assert np.array_equal(audio[:3200], preroll)


def test_max_utterance_caps_runaway_recording(cfg):
    cfg["audio"]["max_utterance_sec"] = 1.0
    ep = Endpointer(cfg)
    mic = FakeMic([speech_block() for _ in range(200)])
    audio = ep.record(mic)
    assert len(audio) / 16000 <= 1.2


def test_mic_dropout_ends_recording(cfg):
    ep = Endpointer(cfg)
    mic = FakeMic([speech_block() for _ in range(6)])  # then read() returns None
    audio = ep.record(mic)
    assert len(audio) > 0


def test_level_callback_receives_normalized_values(cfg):
    ep = Endpointer(cfg)
    mic = FakeMic([speech_block() for _ in range(5)] + [silence_block() for _ in range(20)])
    levels = []
    ep.record(mic, on_level=levels.append)
    assert levels
    assert all(0.0 <= lvl <= 1.0 for lvl in levels)


# -- event bus -------------------------------------------------------------
def test_bus_delivers_to_all_subscribers():
    bus = Bus()
    seen_a, seen_b = [], []
    bus.subscribe(lambda e: seen_a.append(e.kind))
    bus.subscribe(lambda e: seen_b.append(e.payload))
    bus.publish("state", State.LISTENING)
    assert seen_a == ["state"] and seen_b == [State.LISTENING]


def test_a_broken_subscriber_cannot_break_the_voice_loop():
    """A UI exception must never propagate into the audio thread."""
    bus = Bus()
    survivor = []
    bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("UI exploded")))
    bus.subscribe(lambda e: survivor.append(e.kind))
    bus.publish("state", State.IDLE)  # must not raise
    assert survivor == ["state"]
