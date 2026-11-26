import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from trackjudge import media
from trackjudge.app import main
from trackjudge.dsp import _frame_psd, audio_to_float


def test_unsigned_pcm_silence_is_centered():
    np.testing.assert_array_equal(
        audio_to_float(np.array([0, 128, 255], dtype="u1")), [-1, 0, 127 / 128]
    )


def test_frame_density_matches_periodic_hann_reference():
    from scipy.signal import spectrogram

    mono = np.random.default_rng(22).normal(size=420_031).astype("float32")
    f, t, reference = spectrogram(mono, 44_100, window="hann", nperseg=4096, noverlap=2048)
    frequencies, centers, actual = _frame_psd(mono, 44_100)
    np.testing.assert_array_equal(frequencies, f)
    np.testing.assert_array_equal(centers, t)
    np.testing.assert_allclose(actual, reference, rtol=2e-5, atol=3e-11)


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg tools are required"
)
def test_unknown_duration_still_limits_decode_and_keeps_native_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "ANALYSIS_MAX_SECONDS", 0.25)
    source = tmp_path / "native.wav"
    wavfile.write(source, 22050, np.zeros((22050, 2), dtype="float32"))
    output = media.convert_to_wav(str(source), duration=0.0, channels=2, sample_rate=22050)
    rate, samples = wavfile.read(output)
    assert rate == 22050
    assert samples.shape in {(5512, 2), (5513, 2)}


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg tools are required"
)
def test_mixed_good_bad_candidates_leave_inputs_intact(tmp_path):
    good = tmp_path / "音 track.wav"
    bad = tmp_path / "broken.wav"
    wavfile.write(good, 44100, np.random.default_rng(4).uniform(-1, 1, 44100).astype("float32"))
    bad.write_bytes(b"invalid audio")
    before = good.read_bytes()
    result = tmp_path / "result"
    assert main(["--output", str(result), "--json-report", "--", str(bad), str(good)]) == 0

    report = json.loads((result / "trackjudge-report.json").read_text(encoding="utf-8"))
    assert report["winner"]["file_name"] == good.name
    assert [item["url"] for item in report["failures"]] == [str(bad)]
    assert (result / good.name).read_bytes() == good.read_bytes() == before
    assert bad.read_bytes() == b"invalid audio"
    assert not Path(str(good) + ".wav").exists()


def test_concurrent_exports_use_distinct_filenames(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    source = tmp_path / "figure.png"
    source.write_bytes(b"image bytes")
    with ThreadPoolExecutor(max_workers=4) as pool:
        copies = list(pool.map(lambda _: media.copy_artifact(str(source), str(output)), range(8)))
    assert len(set(copies)) == 8
    assert all(Path(item).read_bytes() == source.read_bytes() for item in copies)


def test_inverted_stereo_remains_analyzable(tmp_path):
    from trackjudge.dsp import analyze_file

    signal = np.random.default_rng(13).uniform(-1, 1, 48000).astype("float32")
    path = tmp_path / "inverted.wav"
    wavfile.write(path, 48000, np.column_stack([signal, -signal]))
    result = analyze_file(str(path), None)
    assert result["valid"]
    assert result["correlation"] == pytest.approx(-1.0)
    assert any("гасятся" in message for message in result["warnings"])
