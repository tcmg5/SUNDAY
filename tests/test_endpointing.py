"""Endpointing decides when you've stopped talking. Getting it wrong is the
difference between a usable assistant and one that interrupts you constantly."""
import numpy as np
import pytest

from jarvis.audio.vad import ABSOLUTE_FLOOR, EnergyVAD, Endpointer, make_detector
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
            "prefer_webrtcvad": False,   # exercise the built-in detector
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


# ── the built-in voice detector ──────────────────────────────────────────
def noise(rms: float, n: int = 480, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0, rms, n).astype(np.int16)


def syllables(count: int, base: float = 3500) -> list[np.ndarray]:
    """Amplitude-modulated noise: speech-shaped, with inter-word dips."""
    rng = np.random.default_rng(1)
    out = []
    for i in range(count):
        envelope = 0.35 + 0.65 * abs(np.sin(i * 0.55))
        if i % 17 in (0, 1):
            envelope = 0.06
        out.append(rng.normal(0, base * envelope, 480).astype(np.int16))
    return out


def detect(vad: EnergyVAD, frames) -> str:
    return "".join("1" if vad.is_speech(f) else "0" for f in frames)


def test_detects_speech_present_in_the_very_first_frame():
    """Regression: seeding the noise floor from frame one set it at speaking
    volume and detected nothing. The recorder prepends a pre-roll buffer, so
    frame one is routinely already speech."""
    vad = EnergyVAD(16000, 2)
    assert vad.is_speech(noise(4000)), "speech in the opening frame was missed"


def test_silence_is_never_speech():
    vad = EnergyVAD(16000, 2)
    assert detect(vad, [np.zeros(480, np.int16)] * 30) == "0" * 30


def test_low_rumble_is_not_speech():
    """A DC-ish hum is loud but barely crosses zero."""
    vad = EnergyVAD(16000, 2)
    rumble = (np.sin(np.arange(480) * 0.01) * 900).astype(np.int16)
    assert detect(vad, [rumble] * 30) == "0" * 30


def test_adapts_to_a_noisy_room():
    """Constant fan noise must stop reading as speech once the floor adapts."""
    vad = EnergyVAD(16000, 2)
    result = detect(vad, [noise(900, seed=i) for i in range(40)])
    assert result[-15:] == "0" * 15, f"fan noise still reads as speech: {result}"


def test_speech_still_detected_over_a_noisy_room():
    vad = EnergyVAD(16000, 2)
    detect(vad, [noise(900, seed=i) for i in range(40)])       # settle
    loud = detect(vad, [noise(9000, seed=i) for i in range(10)])
    assert loud.count("1") >= 8, f"speech lost against room noise: {loud}"


def test_long_utterance_never_looks_like_a_full_second_of_silence():
    """The endpointer cuts after ~1s of silence, so any internal gap during
    continuous speech must stay far below that or it truncates people."""
    vad = EnergyVAD(16000, 2)
    result = detect(vad, syllables(166))          # ~5 seconds
    longest_gap = max((len(run) for run in result.split("1")), default=0)
    assert longest_gap * 0.03 < 0.5, f"{longest_gap} frame gap inside speech"
    assert result.count("1") / len(result) > 0.6


def test_absolute_floor_blocks_very_quiet_audio():
    vad = EnergyVAD(16000, 2)
    assert not vad.is_speech(noise(ABSOLUTE_FLOOR / 4))


def test_aggressiveness_raises_the_bar():
    quiet, strict = EnergyVAD(16000, 0), EnergyVAD(16000, 3)
    assert strict.margin_db > quiet.margin_db


def test_reset_clears_the_room_estimate():
    vad = EnergyVAD(16000, 2)
    detect(vad, [noise(3000, seed=i) for i in range(30)])
    vad.reset()
    assert vad.noise_db == EnergyVAD.INITIAL_NOISE_DB


def test_make_detector_falls_back_when_webrtcvad_is_absent():
    assert isinstance(make_detector(16000, 2, prefer_webrtc=False), EnergyVAD)
    # Even when preferred, an uninstalled webrtcvad must not raise.
    assert make_detector(16000, 2, prefer_webrtc=True) is not None
