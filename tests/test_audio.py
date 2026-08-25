"""The DSP that turns clean TTS into something that sounds like a room."""
import numpy as np

from jarvis.audio.stt import to_wav_bytes
from jarvis.audio.tts import (
    apply_jarvis_filter, multitap_reverb, one_pole_highpass, parse_voice_id, presence_tilt,
)


def tone(freq: float, seconds: float = 0.25, rate: int = 22050) -> np.ndarray:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_filter_preserves_length_and_headroom():
    out = apply_jarvis_filter(tone(440), 22050)
    assert len(out) == len(tone(440))
    assert np.max(np.abs(out)) <= 1.0
    assert out.dtype == np.float32


def rms(x, skip=0.25):
    """RMS over the steady-state part, skipping the filter's startup transient."""
    return float(np.sqrt(np.mean(x[int(len(x) * skip):] ** 2)))


def test_highpass_response_matches_a_one_pole_curve():
    """-3 dB at the corner, rolling off 6 dB/octave below it."""
    rate = 22050
    cutoff = 120
    gains = {}
    for freq in (30, 60, 120, 1000):
        signal = tone(freq, 0.5, rate)
        gains[freq] = rms(one_pole_highpass(signal, rate, cutoff)) / rms(signal)

    assert 0.6 < gains[120] < 0.8            # ≈ -3 dB at the corner
    assert gains[1000] > 0.95                # passband essentially untouched
    assert gains[30] < gains[60] < gains[120]  # monotonic roll-off below it


def test_highpass_is_a_noop_when_disabled():
    signal = tone(100)
    assert np.array_equal(one_pole_highpass(signal, 22050, 0), signal)


def test_presence_tilt_boosts_highs_relative_to_lows():
    rate = 22050
    low_gain = rms(presence_tilt(tone(200, 0.5, rate))) / rms(tone(200, 0.5, rate))
    high_gain = rms(presence_tilt(tone(5000, 0.5, rate))) / rms(tone(5000, 0.5, rate))
    assert high_gain > low_gain


def test_full_filter_normalizes_output_level():
    """Loud and quiet input should come back at the same playback level."""
    loud = apply_jarvis_filter(tone(440) * 1.8, 22050)
    quiet = apply_jarvis_filter(tone(440) * 0.05, 22050)
    assert abs(np.max(np.abs(loud)) - np.max(np.abs(quiet))) < 0.01
    assert np.max(np.abs(loud)) <= 0.93


def test_reverb_places_taps_after_the_impulse():
    rate = 22050
    impulse = np.zeros(rate // 2, dtype=np.float32)
    impulse[100] = 1.0
    wet = multitap_reverb(impulse, rate, amount=0.4)
    # The first tap is at 23ms; before that the signal must still be dry.
    assert np.max(np.abs(wet[101 : 100 + int(rate * 0.02)])) == 0.0
    tail = wet[100 + int(rate * 0.02) : 100 + int(rate * 0.15)]
    assert np.max(np.abs(tail)) > 0.01


def test_reverb_is_a_noop_when_amount_is_zero():
    signal = tone(440)
    assert np.array_equal(multitap_reverb(signal, 22050, 0.0), signal)


def test_reverb_tail_decays():
    rate = 22050
    impulse = np.zeros(rate // 2, dtype=np.float32)
    impulse[0] = 1.0
    wet = multitap_reverb(impulse, rate, amount=0.5)
    taps = [abs(wet[int(rate * ms / 1000)]) for ms, _ in [(23, 0), (41, 0), (67, 0), (97, 0)]]
    assert taps == sorted(taps, reverse=True), "later reflections must be quieter"


def test_filter_handles_empty_input():
    assert len(apply_jarvis_filter(np.zeros(0, dtype=np.float32), 22050)) == 0


def test_parse_voice_id():
    assert parse_voice_id("en_GB-alan-medium") == ("en", "en_GB", "alan", "medium")
    assert parse_voice_id("en_US-ryan-high") == ("en", "en_US", "ryan", "high")


def test_wav_encoding_roundtrip():
    samples = (tone(440, 0.1, 16000) * 32767).astype(np.int16)
    wav = to_wav_bytes(samples, 16000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    decoded = np.frombuffer(wav[44:], dtype=np.int16)
    assert np.array_equal(decoded, samples)
