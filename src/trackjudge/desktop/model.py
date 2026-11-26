from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from ..app import build_parser

URL_PATTERN = re.compile(
    r"https?://.*?(?=(?:https?://)|[\s<>'\"\[\]]|$)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class GuiRunConfig:
    sources: tuple[str, ...]
    output_folder: str
    save_spectrogram: bool = True
    save_json_report: bool = True
    use_browser_cookies: bool = True
    spectrogram_folder: str | None = None


def extract_sources(text: str) -> list[str]:
    """Extract unique URLs, including URLs pasted immediately one after another."""
    sources: list[str] = []
    for match in URL_PATTERN.finditer(text):
        value = match.group(0).strip().rstrip(".,;:!?)]}")
        if value and value not in sources:
            sources.append(value)
    return sources


def shorten_path(path: str | None, max_length: int = 72) -> str:
    if not path:
        return ""
    if len(path) <= max_length:
        return path
    value = PureWindowsPath(path) if "\\" in path else Path(path)
    anchor = value.anchor.rstrip("\\/")
    tail = str(Path(value.parent.name) / value.name)
    compact = f"{anchor}\\…\\{tail}" if anchor else f"…\\{tail}"
    if len(compact) <= max_length:
        return compact
    keep = max(12, max_length - len(anchor) - 5)
    return f"{anchor}\\…\\{value.name[-keep:]}"


def candidate_explanation(candidate: dict[str, Any], language: str = "ru") -> str:
    cutoff = float(candidate.get("effective_cutoff_hz", 0.0))
    raw_cutoff = float(candidate.get("raw_cutoff_hz", 0.0))
    score = float(candidate.get("score", 0.0))
    authenticity = float(candidate.get("authenticity", 0.0))
    reasons: list[str] = []

    language = language if language in ("ru", "en", "de") else "ru"
    if candidate.get("fake_noise") and language == "ru":
        reasons.append(
            "Выше полезного среза обнаружена почти неподвижная шумовая полка: "
            "высокие частоты выглядят добавленными искусственно."
        )
    elif candidate.get("fake_noise") and language == "en":
        reasons.append(
            "A nearly static noise shelf was found above the useful cutoff; "
            "the high frequencies appear to have been added artificially."
        )
    elif candidate.get("fake_noise"):
        reasons.append(
            "Oberhalb des nutzbaren Cutoffs wurde ein fast statisches Rauschband erkannt; "
            "die hohen Frequenzen wirken künstlich hinzugefügt."
        )
    elif cutoff < 15_500 and language == "ru":
        reasons.append(
            f"Полезный спектр заканчивается примерно на {cutoff / 1000:.1f} кГц — "
            "это характерный признак источника низкого качества или апскейла."
        )
    elif cutoff < 15_500 and language == "en":
        reasons.append(
            f"The useful spectrum ends at about {cutoff / 1000:.1f} kHz, "
            "a common sign of a low-quality source or an upscale."
        )
    elif cutoff < 15_500:
        reasons.append(
            f"Das nutzbare Spektrum endet bei etwa {cutoff / 1000:.1f} kHz — "
            "ein typisches Zeichen für eine minderwertige Quelle oder ein Upscale."
        )
    elif cutoff < 17_500 and language == "ru":
        reasons.append(
            f"Заметный ранний срез около {cutoff / 1000:.1f} кГц ограничивает детализацию "
            "верхнего диапазона."
        )
    elif cutoff < 17_500 and language == "en":
        reasons.append(
            f"A clear early cutoff near {cutoff / 1000:.1f} kHz limits upper-range detail."
        )
    elif cutoff < 17_500:
        reasons.append(
            f"Ein deutlicher früher Cutoff bei {cutoff / 1000:.1f} kHz begrenzt die Details "
            "im oberen Frequenzbereich."
        )
    elif cutoff < 19_000 and language == "ru":
        reasons.append(
            f"Верхний диапазон ослабевает около {cutoff / 1000:.1f} кГц; "
            "качество приемлемое, но уступает более полному спектру."
        )
    elif cutoff < 19_000 and language == "en":
        reasons.append(
            f"The upper range fades near {cutoff / 1000:.1f} kHz; quality is acceptable "
            "but below a fuller spectrum."
        )
    elif cutoff < 19_000:
        reasons.append(
            f"Der obere Bereich fällt bei etwa {cutoff / 1000:.1f} kHz ab; die Qualität "
            "ist brauchbar, liegt aber unter einem vollständigeren Spektrum."
        )
    elif language == "ru":
        reasons.append(
            f"Полезный спектр сохраняется примерно до {cutoff / 1000:.1f} кГц "
            "без явного раннего среза."
        )
    elif language == "en":
        reasons.append(
            f"The useful spectrum extends to about {cutoff / 1000:.1f} kHz "
            "without an obvious early cutoff."
        )
    else:
        reasons.append(
            f"Das nutzbare Spektrum reicht bis etwa {cutoff / 1000:.1f} kHz, "
            "ohne erkennbaren frühen Cutoff."
        )

    if raw_cutoff - cutoff > 1_500 and not candidate.get("fake_noise"):
        reasons.append(
            {
                "ru": "Энергия выше полезного среза есть, но она слабо похожа на музыкальный сигнал.",
                "en": "There is energy above the useful cutoff, but it barely resembles musical content.",
                "de": "Oberhalb des nutzbaren Cutoffs ist Energie vorhanden, sie ähnelt jedoch kaum einem Musiksignal.",
            }[language]
        )
    if authenticity < 45:
        template = {
            "ru": "Достоверность высокочастотного содержимого низкая: {value:.0f}/100.",
            "en": "High-frequency content authenticity is low: {value:.0f}/100.",
            "de": "Die Authentizität des Hochfrequenzinhalts ist niedrig: {value:.0f}/100.",
        }[language]
        reasons.append(template.format(value=authenticity))
    elif score >= 70:
        template = {
            "ru": "Итоговая спектральная оценка высокая: {value:.1f}/100.",
            "en": "The final spectral score is high: {value:.1f}/100.",
            "de": "Die abschließende Spektralbewertung ist hoch: {value:.1f}/100.",
        }[language]
        reasons.append(template.format(value=score))

    warnings = [str(item) for item in candidate.get("warnings", []) if str(item).strip()]
    if language == "ru":
        reasons.extend(warnings[:2])
    return " ".join(reasons)


def build_gui_namespace(config: GuiRunConfig, report_path: str) -> argparse.Namespace:
    """Translate GUI selections into the same arguments used by the CLI."""
    parser = build_parser()
    argv = [
        *config.sources,
        "--output",
        config.output_folder,
        "--json-report",
        report_path,
        "--pause",
        "0",
        "--browser-cookies",
        "auto" if config.use_browser_cookies else "off",
        "--no-color",
    ]
    if config.save_spectrogram:
        argv.extend(["--spectrogram", "--keep-loser-spectrograms"])
        if config.spectrogram_folder:
            argv.extend(["--spectrogram-dir", config.spectrogram_folder])
    args = parser.parse_args(argv)
    return args
