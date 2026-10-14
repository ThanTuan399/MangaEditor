from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time

from .base import OcrRequest
from .pipeline import OcrPipeline


@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    id: str
    image: str
    truth: str
    language: str = "ja"
    layout: str = "auto"
    tags: tuple[str, ...] = ()
    notes: str = ""


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def compact_text(text: str) -> str:
    return "".join(normalize_newlines(text).split())


def levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (char_a != char_b),
                )
            )
        previous = current
    return previous[-1]


def character_error_rate(truth: str, prediction: str) -> float:
    truth = normalize_newlines(truth)
    prediction = normalize_newlines(prediction)
    if not truth:
        return 0.0 if not prediction else 1.0
    return levenshtein_distance(truth, prediction) / len(truth)


def compact_character_error_rate(truth: str, prediction: str) -> float:
    truth_compact = compact_text(truth)
    pred_compact = compact_text(prediction)
    if not truth_compact:
        return 0.0 if not pred_compact else 1.0
    return levenshtein_distance(truth_compact, pred_compact) / len(truth_compact)


def omitted_truth_lines(truth: str, prediction: str) -> int:
    prediction_compact = compact_text(prediction)
    count = 0
    for line in normalize_newlines(truth).splitlines():
        candidate = compact_text(line)
        if candidate and candidate not in prediction_compact:
            count += 1
    return count


def load_manifest(dataset_dir: str | Path) -> list[BenchmarkSample]:
    root = Path(dataset_dir)
    path = root / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_samples = data.get("samples", data if isinstance(data, list) else [])
    samples = []
    for item in raw_samples:
        samples.append(
            BenchmarkSample(
                id=str(item["id"]),
                image=str(item["image"]),
                truth=str(item["truth"]),
                language=str(item.get("language", "ja")),
                layout=str(item.get("layout", "auto")),
                tags=tuple(item.get("tags", [])),
                notes=str(item.get("notes", "")),
            )
        )
    return samples


def run_benchmark(
    dataset_dir: str | Path,
    *,
    engine: str = "auto",
    preprocess: str = "original",
    pipeline: OcrPipeline | None = None,
) -> dict:
    root = Path(dataset_dir)
    samples = load_manifest(root)
    pipeline = pipeline or OcrPipeline()

    results = []
    for sample in samples:
        image_path = root / sample.image
        started = time.perf_counter()
        error = ""
        prediction = ""
        result_engine = ""
        warning = ""
        suspicions = []
        metadata = {}
        try:
            result = pipeline.recognize(
                OcrRequest(
                    image_bytes=image_path.read_bytes(),
                    language=sample.language,
                    layout=sample.layout,
                    options={
                        "engine": engine,
                        "preprocess": preprocess,
                    },
                )
            )
            prediction = result.text
            result_engine = result.engine
            warning = result.warning
            metadata = dict(result.metadata)
            suspicions = list(metadata.get("suspicions", []))
        except Exception as exc:
            error = str(exc)

        duration_ms = int((time.perf_counter() - started) * 1000)
        results.append(
            {
                "id": sample.id,
                "image": sample.image,
                "language": sample.language,
                "layout": sample.layout,
                "tags": list(sample.tags),
                "truth": sample.truth,
                "prediction": prediction,
                "engine": result_engine,
                "requested_engine": engine,
                "preprocess": preprocess,
                "cer": character_error_rate(sample.truth, prediction),
                "cer_compact": compact_character_error_rate(
                    sample.truth, prediction
                ),
                "omitted_truth_lines": omitted_truth_lines(
                    sample.truth, prediction
                ),
                "duration_ms": duration_ms,
                "warning": warning,
                "suspicions": suspicions,
                "error": error,
                "metadata": metadata,
            }
        )

    success = [row for row in results if not row["error"]]
    mean_cer = (
        sum(row["cer"] for row in success) / len(success)
        if success else None
    )
    mean_compact_cer = (
        sum(row["cer_compact"] for row in success) / len(success)
        if success else None
    )
    total_ms = sum(row["duration_ms"] for row in results)

    return {
        "dataset": str(root),
        "requested_engine": engine,
        "preprocess": preprocess,
        "sample_count": len(results),
        "success_count": len(success),
        "mean_cer": mean_cer,
        "mean_compact_cer": mean_compact_cer,
        "total_duration_ms": total_ms,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark OCR MangaEditor bằng bản chép đúng."
    )
    parser.add_argument("dataset", help="Thư mục có manifest.json")
    parser.add_argument(
        "--engine",
        default="auto",
        choices=["auto", "tesseract", "mangaocr"],
    )
    parser.add_argument(
        "--preprocess",
        default="original",
        choices=["original", "upscale2x", "contrast", "manga_clean"],
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = run_benchmark(
        args.dataset,
        engine=args.engine,
        preprocess=args.preprocess,
    )

    output = args.output or str(
        Path(args.dataset)
        / f"report-{args.engine}-{args.preprocess}.json"
    )
    Path(output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    mean = report["mean_cer"]
    compact = report["mean_compact_cer"]
    print(f"Samples: {report['sample_count']}")
    print(f"Success: {report['success_count']}")
    print(
        "Mean CER: "
        + ("n/a" if mean is None else f"{mean:.4f}")
    )
    print(
        "Mean compact CER: "
        + ("n/a" if compact is None else f"{compact:.4f}")
    )
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
