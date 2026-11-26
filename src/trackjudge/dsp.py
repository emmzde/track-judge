from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.io import wavfile
from scipy.signal import butter, get_window, sosfiltfilt

from .spectrum import HAS_MPL, render_spectrogram

MIN_RELIABLE_DURATION = 20.0
MIN_HARD_DURATION = 5.0
EPS = 1e-20

# --- Параметры DSP ---------------------------------------------------------
STFT_NPERSEG = 4096  # частотное разрешение ~10.8 Гц @ 44.1 кГц
PRESENCE_DB = -55.0  # порог "энергия присутствует" относительно опоры (dB)
CUTOFF_LOW_HZ = 15000.0
CUTOFF_HIGH_HZ = 19500.0


def empty_metrics(reason: str | None = None) -> dict[str, Any]:
    warnings = [reason] if reason else []
    return {
        "duration": 0.0,
        "cutoff": 0.0,
        "raw_cutoff": 0.0,
        "cliff_db_per_khz": 0.0,
        "flatness": 0.0,
        "hf_db": -120.0,
        "hf_ratio": 0.0,
        "modulation": 0.0,
        "env_corr": None,
        "correlation": None,
        "authenticity": 0.0,
        "fake_noise": False,
        "score": 0.0,
        "raw_score": 0.0,
        "reliable": False,
        "valid": False,
        "warnings": warnings,
        "spectrogram": None,
    }


def audio_to_float(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data)
    if np.issubdtype(arr.dtype, np.integer):
        midpoint = float(2 ** (arr.dtype.itemsize * 8 - 1))
        signed = arr.astype(np.float32)
        if arr.dtype.kind == "u":
            signed -= midpoint
        return signed / midpoint
    arr = arr.astype(np.float32, copy=False)
    if not np.isfinite(arr).all():
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return arr


def spectral_flatness(psd: np.ndarray) -> float:
    psd = np.asarray(psd, dtype=float)
    psd = psd[np.isfinite(psd)]
    if psd.size == 0:
        return 0.0
    psd = np.maximum(psd, EPS)
    arithmetic = float(np.mean(psd))
    if arithmetic <= EPS:
        return 0.0
    geometric = float(np.exp(np.mean(np.log(psd))))
    return float(np.clip(geometric / arithmetic, 0.0, 1.0))


def apply_duration_cap(score: float, duration: float, min_reliable_duration: float) -> float:
    if duration >= min_reliable_duration:
        return score
    if duration <= MIN_HARD_DURATION:
        cap = 35.0
    else:
        span = max(min_reliable_duration - MIN_HARD_DURATION, 1.0)
        cap = 35.0 + np.clip((duration - MIN_HARD_DURATION) / span, 0.0, 1.0) * 40.0
    return float(min(score, cap))


def safe_correlation(first: np.ndarray, second: np.ndarray) -> float | None:
    first_std = float(np.std(first))
    second_std = float(np.std(second))
    if (
        not math.isfinite(first_std)
        or not math.isfinite(second_std)
        or first_std <= 1e-12
        or second_std <= 1e-12
    ):
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = float(np.corrcoef(first, second)[0, 1])
    if not math.isfinite(correlation):
        return None
    return float(np.clip(correlation, -1.0, 1.0))


def _band_correlation(data: np.ndarray, fs: int, low: float, high: float) -> float | None:
    """Accumulate Pearson moments over guarded blocks of zero-phase filtered stereo."""
    if high <= low:
        return None
    sos = butter(4, [low, high], fs=fs, btype="bandpass", output="sos")
    block = 65536
    # The guard covers the filter's settling time even for narrow probe bands.
    guard = max(512, math.ceil(16 * fs / (high - low)))
    sx = sy = xx = yy = xy = 0.0
    for start in range(0, len(data), block):
        end = min(len(data), start + block)
        lo = max(0, start - guard)
        hi = min(len(data), end + guard)
        pair = sosfiltfilt(sos, data[lo:hi, :2], axis=0)[start - lo : end - lo]
        x, y = pair.T
        sx += x.sum()
        sy += y.sum()
        xx += np.einsum("i,i->", x, x)
        yy += np.einsum("i,i->", y, y)
        xy += np.einsum("i,i->", x, y)
    n = len(data)
    vx, vy = xx - sx * sx / n, yy - sy * sy / n
    if min(vx, vy) <= n * 1e-24:
        return None
    return float(np.clip((xy - sx * sy / n) / math.sqrt(vx * vy), -1, 1))


def _frame_psd(mono: np.ndarray, fs: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Periodic Hann, 50% overlap and one-sided density, using only complete frames."""
    size = STFT_NPERSEG
    hop = size // 2
    windows = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop]
    taper = get_window("hann", size).astype(np.float32)
    scale = 1 / (fs * np.sum(taper**2))
    power = np.empty((size // 2 + 1, len(windows)), dtype=np.float32)
    for start in range(0, len(windows), 64):
        frames = windows[start : start + 64]
        windowed = (frames - frames.mean(axis=1, keepdims=True)) * taper
        value = np.abs(rfft(windowed, axis=1)) ** 2
        value *= scale
        value[:, 1:-1] *= 2
        power[:, start : start + len(frames)] = value.T
    return rfftfreq(size, 1 / fs), (np.arange(len(windows)) * hop + size / 2) / fs, power


def analyze_file(
    wav_path: str,
    spectrogram_path: str | None,
    min_reliable_duration: float = MIN_RELIABLE_DURATION,
    track_label: str = "",
) -> dict[str, Any]:
    """Спектральный анализ через STFT по суб-полосам.

    Ключевая идея против фейковых ВЧ: реальный музыкальный верх МОДУЛИРУЕТСЯ во времени
    (транзиенты тарелок/хэтов), а подмешанный шум стационарен. "Эффективный срез" считается
    по последней суб-полосе с живым (модулированным) сигналом, шумовой хвост игнорируется.
    """
    try:
        try:
            fs, raw_data = wavfile.read(wav_path, mmap=True)
        except ValueError:
            # Packed 24-bit PCM cannot be memory-mapped by scipy.io.wavfile.
            fs, raw_data = wavfile.read(wav_path)
    except Exception as exc:
        return empty_metrics(f"не удалось прочитать WAV: {exc}")

    data = audio_to_float(raw_data)
    if data.size == 0 or fs <= 0:
        return empty_metrics("пустой или некорректный PCM")

    is_stereo = data.ndim == 2 and data.shape[1] > 1
    mono = data.mean(axis=1, dtype=np.float32) if is_stereo else data.reshape(-1)

    duration = float(len(mono) / fs)
    warnings: list[str] = []
    if len(mono) < STFT_NPERSEG:
        metrics = empty_metrics("слишком мало PCM-сэмплов для STFT")
        metrics["duration"] = duration
        return metrics
    if is_stereo:
        # Opposite polarity can cancel a valid stereo recording in a mono fold-down.
        channel_energy = np.einsum("ij,ij->j", data, data, dtype=np.float64)
        loudest = int(channel_energy.argmax())
        mono_energy = np.einsum("i,i->", mono, mono, dtype=np.float64)
        if mono_energy < 1e-6 * channel_energy[loudest]:
            mono = data[:, loudest]
            warnings.append(
                "Каналы взаимно гасятся при сложении. Спектр измерен по отдельному каналу."
            )
    if duration < min_reliable_duration:
        warnings.append(
            f"короткий файл: {duration:.2f} с, надежный анализ требует примерно "
            f"{min_reliable_duration:.0f} с"
        )

    nyq = 0.5 * fs
    if nyq <= 16000.0:
        warnings.append(
            "частота дискретизации не дает проверить полосу выше 16 kHz; "
            "probe-анализ ВЧ отключён, authenticity = 50 (нейтраль)"
        )

    # --- STFT ------------------------------------------------------------
    f, t, Sxx = _frame_psd(mono, fs)
    # Row batches preserve the exact median without copying the entire PSD.
    psd_med = np.concatenate([np.median(batch, axis=1) for batch in np.array_split(Sxx, 16)])

    ref_mask = (f >= 1000.0) & (f <= 5000.0)
    if not np.any(ref_mask):
        ref_mask = (f >= 200.0) & (f <= min(6000.0, 0.5 * nyq))
    ref_level = (
        float(np.median(psd_med[ref_mask])) if np.any(ref_mask) else float(np.median(psd_med))
    )
    if ref_level <= EPS:
        metrics = empty_metrics("сигнал близок к цифровой тишине")
        metrics["duration"] = duration
        return metrics

    # Сглаженный спектр и dB-кривая относительно опоры.
    psd_s = np.convolve(psd_med, np.ones(5) / 5.0, mode="same") if len(psd_med) >= 5 else psd_med
    db_curve = 10.0 * np.log10(np.maximum(psd_s, EPS) / ref_level)

    # --- Энергетический срез (вся полоса, включая возможный шум) ---------
    # Метод "dB ниже опоры" (как в Spek): квантизационный пол сидит ниже -55 дБ
    # и отсекается сам, а настоящий тихий ВЧ — нет. Доп. абсолютный пол страхует
    # от цифровой тишины.
    present_thr = ref_level * 10 ** (PRESENCE_DB / 10.0)
    abs_floor = float(np.max(psd_s)) * 1e-7
    valid = (psd_s > present_thr) & (psd_s > abs_floor) & (f > 1000.0)
    valid_idx = np.where(valid)[0]
    raw_cutoff = float(f[valid_idx[-1]]) if len(valid_idx) else 1000.0

    # --- Probe-полоса 16.5..20 кГц: тут живёт шум "раздутого MP3" --------
    probe_lo = 16500.0
    probe_hi = min(20000.0, 0.95 * nyq)
    p_level_db = -120.0
    p_flatness = 0.0
    p_modulation = 0.0
    p_env_corr: float | None = None
    if probe_hi > probe_lo:
        probe_mask = (f >= probe_lo) & (f <= probe_hi)
        if np.any(probe_mask):
            p_energy = float(np.mean(psd_med[probe_mask]))
            p_level_db = 10.0 * np.log10(max(p_energy, EPS) / ref_level)
            p_flatness = spectral_flatness(psd_med[probe_mask])
            mid_env_mask = (f >= 500.0) & (f <= 4000.0)
            if Sxx.shape[1] >= 8 and np.any(mid_env_mask):
                probe_env = Sxx[probe_mask, :].mean(axis=0)
                mid_env = Sxx[mid_env_mask, :].mean(axis=0)
                if np.mean(probe_env) > EPS:
                    p_modulation = float(np.std(probe_env) / (np.mean(probe_env) + EPS))
                    lp = np.log10(probe_env + EPS)
                    lm = np.log10(mid_env + EPS)
                    p_env_corr = safe_correlation(lp, lm)

    # Корреляция каналов строго в probe-полосе (независимый шум => ~0).
    p_lr_corr = _band_correlation(data, fs, probe_lo, probe_hi) if is_stereo else None
    lr_corr = _band_correlation(data, fs, 14000.0, probe_hi) if is_stereo else None

    # --- Классификация probe-полосы: пусто / настоящее / шум -------------
    probe_has_energy = p_level_db > -50.0
    # L/R-корреляция одна не достаточна: коррелированный шум (L==R) даёт
    # p_lr_corr ≈ 1.0, но модуляция будет низкой. Требуем либо env_corr,
    # либо L/R + модуляцию совместно.
    genuine_hf = (
        (p_env_corr is not None and p_env_corr > 0.20)
        or (p_lr_corr is not None and p_lr_corr > 0.40 and p_modulation > 0.25)
        or (p_modulation > 0.45 and p_flatness < 0.50)
    )
    noiselike_hf = (
        probe_has_energy
        and p_flatness > 0.50
        and p_modulation < 0.35
        and (p_env_corr is None or p_env_corr < 0.20)
        # L/R корреляция снимает подозрение в шуме, НО только если сигнал
        # хоть немного модулирован (> 0.15). Коррелированный шум (L==R)
        # даёт p_lr_corr ≈ 1.0, но остаётся стационарным (modulation < 0.15).
        and (p_lr_corr is None or abs(p_lr_corr) < 0.25 or p_modulation < 0.15)
    )
    fake_noise = bool(noiselike_hf and not genuine_hf and raw_cutoff > 16000.0)

    # --- Честный срез: при фейке игнорируем шумовую "полку" --------------
    if fake_noise:
        below_idx = np.where(valid & (f < probe_lo))[0]
        eff_cutoff = float(f[below_idx[-1]]) if len(below_idx) else 1000.0
        eff_cutoff = min(eff_cutoff, 16500.0)
    else:
        eff_cutoff = raw_cutoff

    # --- Крутизна обрыва (brick-wall lossy) -----------------------------
    cliff_db_per_khz = 0.0
    if 1000.0 < eff_cutoff < nyq - 1000.0:
        i_lo = int(np.argmin(np.abs(f - (eff_cutoff - 300.0))))
        i_hi = int(np.argmin(np.abs(f - (eff_cutoff + 1000.0))))
        if i_hi > i_lo:
            cliff_db_per_khz = float((db_curve[i_lo] - db_curve[i_hi]) / 1.3)

    # --- Метрики ВЧ-зоны 16..20 кГц для отчёта ---------------------------
    hf_lo = 16000.0
    hf_hi = min(20000.0, 0.95 * nyq)
    hf_db = -120.0
    hf_ratio = 0.0
    flatness = p_flatness
    if hf_hi > hf_lo:
        hf_mask = (f >= hf_lo) & (f <= hf_hi)
        if np.any(hf_mask):
            hf_energy = float(np.mean(psd_med[hf_mask]))
            hf_ratio = float(np.clip(hf_energy / (ref_level + EPS), 0.0, 1.0))
            hf_db = 10.0 * np.log10(max(hf_energy, EPS) / ref_level)

    modulation = p_modulation
    env_corr = p_env_corr

    # --- Authenticity (уверенность, что верх настоящий) 0..100 ----------
    # Эвристические веса разделяют модулированный музыкальный верх и стационарный
    # шум. Они не доказывают происхождение файла и требуют проверки на размеченном
    # корпусе перед использованием в форензике.
    #   AUTH_BASE       = 60.0  — нейтральная точка отсчёта
    #   W_ENV_CORR      = 25.0  — корреляция ВЧ-огибающей с музыкой (важнейший признак)
    #   W_LR_CORR       = 20.0  — стерео-согласованность L/R в probe-полосе
    #   LR_CORR_OFFSET  = 0.3   — сдвиг L/R: случайный шум даёт ~0.3, живой верх > 0.6
    #   W_MODULATION    = 15.0  — вес временно́й модуляции ВЧ (транзиенты тарелок)
    #   FLAT_SENS       = 60.0  — чувствительность к спектральной плоскости
    #   FLAT_THRESHOLD  = 0.50  — порог, выше которого спектр «слишком плоский» (шум)
    AUTH_BASE = 60.0
    W_ENV_CORR = 25.0
    W_LR_CORR = 20.0
    LR_CORR_OFFSET = 0.3
    W_MODULATION = 15.0
    FLAT_SENS = 60.0
    FLAT_THRESHOLD = 0.50

    auth = AUTH_BASE
    if p_env_corr is not None:
        auth += float(np.clip(p_env_corr, -1, 1)) * W_ENV_CORR
    if p_lr_corr is not None:
        auth += (float(np.clip(abs(p_lr_corr), 0, 1)) - LR_CORR_OFFSET) * W_LR_CORR
    auth += float(np.clip(p_modulation, 0.0, 1.0)) * W_MODULATION
    auth -= float(np.clip((p_flatness - FLAT_THRESHOLD) * FLAT_SENS, 0.0, 40.0))
    if not probe_has_energy:
        auth = 50.0  # нет ВЧ для оценки достоверности — нейтрально
    authenticity = float(np.clip(auth, 0.0, 100.0))

    # --- Итоговый скоринг ------------------------------------------------
    # Базис — честная полоса (эффективный срез).
    cutoff_score = float(
        np.clip((eff_cutoff - CUTOFF_LOW_HZ) / (CUTOFF_HIGH_HZ - CUTOFF_LOW_HZ) * 100.0, 0.0, 100.0)
    )
    raw_score = cutoff_score

    # Очень крутой обрыв на средних частотах — подпись lossy-кодека.
    if eff_cutoff < 17500.0 and cliff_db_per_khz > 40.0:
        raw_score *= 0.90

    if fake_noise:
        raw_score = min(raw_score, 22.0)
        warnings.append(
            f"обнаружены фейковые ВЧ: живой сигнал до ~{eff_cutoff / 1000:.1f} кГц, "
            f"выше — стационарный шум до ~{raw_cutoff / 1000:.1f} кГц"
        )

    total_score = apply_duration_cap(raw_score, duration, min_reliable_duration)
    reliable = duration >= min_reliable_duration and eff_cutoff > 1500.0

    metrics = {
        "duration": duration,
        "cutoff": eff_cutoff,
        "raw_cutoff": raw_cutoff,
        "cliff_db_per_khz": cliff_db_per_khz,
        "flatness": flatness,
        "hf_db": hf_db,
        "hf_ratio": hf_ratio,
        "modulation": modulation,
        "env_corr": env_corr,
        "correlation": lr_corr,
        "authenticity": authenticity,
        "fake_noise": fake_noise,
        "score": total_score,
        "raw_score": raw_score,
        "reliable": reliable,
        "valid": True,
        "warnings": warnings,
        "spectrogram": None,
    }

    # --- Спектрограмма ---------------------------------------------------
    if spectrogram_path and HAS_MPL:
        try:
            render_spectrogram(
                f,
                t,
                Sxx,
                ref_level,
                nyq,
                eff_cutoff,
                raw_cutoff,
                fake_noise,
                spectrogram_path,
                track_label,
            )
            metrics["spectrogram"] = spectrogram_path
        except Exception as exc:
            warnings.append(f"не удалось построить спектрограмму: {exc}")

    return metrics
