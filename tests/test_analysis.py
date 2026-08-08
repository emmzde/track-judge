from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from trackjudge.app import (
    HAS_MPL,
    analyze_file,
    apply_duration_cap,
    quality_label,
    render_spectrogram,
    safe_correlation,
)


@pytest.fixture(scope="module")
def spectral_results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, object]]:
    sample_rate = 48_000
    duration = 8
    sample_count = sample_rate * duration
    time_axis = np.arange(sample_count) / sample_rate
    envelope = 0.2 + 0.8 * (0.5 + 0.5 * np.sin(2 * np.pi * 1.7 * time_axis))
    frequencies = np.fft.rfftfreq(sample_count, 1 / sample_rate)
    random = np.random.default_rng(42)

    def band_noise(low_hz: float, high_hz: float) -> np.ndarray:
        spectrum = np.fft.rfft(random.standard_normal(sample_count))
        spectrum[(frequencies < low_hz) | (frequencies > high_hz)] = 0
        return np.fft.irfft(spectrum, sample_count)

    base_left = band_noise(80, 15_000) * envelope
    base_right = 0.85 * base_left + 0.15 * band_noise(80, 15_000) * envelope
    genuine_hf = band_noise(16_500, 20_000) * envelope
    fake_left = band_noise(16_500, 20_000)
    fake_right = band_noise(16_500, 20_000)

    fixtures = {
        "lowpass": np.column_stack((base_left, base_right)),
        "genuine_hf": np.column_stack(
            (base_left + 0.18 * genuine_hf, base_right + 0.18 * genuine_hf)
        ),
        "fake_hf": np.column_stack((base_left + 0.18 * fake_left, base_right + 0.18 * fake_right)),
    }

    output: dict[str, dict[str, object]] = {}
    fixture_dir = tmp_path_factory.mktemp("spectral-fixtures")
    for name, audio in fixtures.items():
        audio = audio / max(float(np.max(np.abs(audio))), 1e-9) * 0.8
        path = Path(fixture_dir) / f"{name}.wav"
        wavfile.write(path, sample_rate, audio.astype(np.float32))
        output[name] = analyze_file(
            str(path),
            spectrogram_path=None,
            min_reliable_duration=5,
            track_label=name,
        )
    return output


def test_spectral_ranking_separates_expected_cases(
    spectral_results: dict[str, dict[str, object]],
) -> None:
    lowpass = spectral_results["lowpass"]
    genuine = spectral_results["genuine_hf"]
    fake = spectral_results["fake_hf"]

    assert lowpass["cutoff"] < 15_500
    assert lowpass["score"] < 15

    assert genuine["cutoff"] > 19_500
    assert genuine["score"] > 90
    assert genuine["fake_noise"] is False

    assert fake["fake_noise"] is True
    assert fake["cutoff"] < 17_000
    assert fake["score"] <= 22


def test_duration_cap_and_labels() -> None:
    assert apply_duration_cap(95, 4, 20) == 35
    assert apply_duration_cap(95, 20, 20) == 95
    assert quality_label(80) == "хорошее качество"
    assert quality_label(80, fake_noise=True) == "фейковые ВЧ (подмешан шум)"


def test_safe_correlation_rejects_constant_or_invalid_results() -> None:
    assert safe_correlation(np.ones(32), np.ones(32)) is None
    assert safe_correlation(np.arange(32), np.arange(32)) == pytest.approx(1.0)


@pytest.mark.skipif(not HAS_MPL, reason="matplotlib is optional")
def test_spectrogram_uses_the_single_application_theme(tmp_path: Path) -> None:
    frequencies = np.linspace(0, 24_000, 96)
    times = np.linspace(0, 8, 64)
    spectrum = np.outer(
        np.linspace(1.0, 0.05, len(frequencies)),
        0.5 + 0.5 * np.sin(times)[None, :].ravel(),
    )
    output = tmp_path / "spectrogram.png"
    render_spectrogram(
        frequencies,
        times,
        spectrum,
        ref_level=1.0,
        nyq=24_000,
        eff_cutoff=19_000,
        raw_cutoff=20_000,
        fake_noise=False,
        out_path=str(output),
        title="Theme verification",
    )
    assert output.is_file()
    assert output.stat().st_size > 0
