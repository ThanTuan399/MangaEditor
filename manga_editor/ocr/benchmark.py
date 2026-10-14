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


def reading_order_score(truth: str, prediction: str) -> float:
    """Điểm 0..1 dựa trên thứ tự các dòng ground-truth trong kết quả."""
    truth_lines = [
        compact_text(line)
        for line in normalize_newlines(truth).splitlines()
        if compact_text(line)
    ]
    if not truth_lines:
        return 1.0
    prediction_compact = compact_text(prediction)
    positions = [
        prediction_compact.find(line)
        for line in truth_lines
    ]
    if len(positions) == 1:
        return 1.0 if positions[0] >= 0 else 0.0

    good = 0
    total = len(positions) - 1
    for left, right in zip(positions, positions[1:]):
        if left >= 0 and right >= 0 and left < right:
            good += 1
    return good / total


def _aggregate_rows(rows: list[dict]) -> dict:
    if not rows:
        return {
            "sample_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "mean_cer": None,
            "mean_compact_cer": None,
            "mean_reading_order_score": None,
            "total_omitted_truth_lines": 0,
            "mean_duration_ms": None,
        }
    success_count = sum(1 for row in rows if not row["error"])
    return {
        "sample_count": len(rows),
        "success_count": success_count,
        "failure_count": len(rows) - success_count,
        "mean_cer": sum(row["cer"] for row in rows) / len(rows),
        "mean_compact_cer": (
            sum(row["cer_compact"] for row in rows) / len(rows)
        ),
        "mean_reading_order_score": (
            sum(row["reading_order_score"] for row in rows) / len(rows)
        ),
        "total_omitted_truth_lines": sum(
            row["omitted_truth_lines"] for row in rows
        ),
        "mean_duration_ms": (
            sum(row["duration_ms"] for row in rows) / len(rows)
        ),
    }


def _group_report(results: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    for row in results:
        keys = [
            f"language:{row['language']}",
            f"layout:{row['layout']}",
        ]
        keys.extend(f"tag:{tag}" for tag in row.get("tags", []))
        for key in keys:
            groups.setdefault(key, []).append(row)
    return {
        key: _aggregate_rows(rows)
        for key, rows in sorted(groups.items())
    }


def load_manifest(dataset_dir: str | Path) -> list[BenchmarkSample]:
    root = Path(dataset_dir)
    path = root / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_samples = data.get("samples", [])
    elif isinstance(data, list):
        raw_samples = data
    else:
        raise ValueError("manifest.json phải là object hoặc danh sách sample.")
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
                "edit_operations": levenshtein_distance(
                    normalize_newlines(sample.truth),
                    normalize_newlines(prediction),
                ),
                "cer": character_error_rate(sample.truth, prediction),
                "cer_compact": compact_character_error_rate(
                    sample.truth, prediction
                ),
                "omitted_truth_lines": omitted_truth_lines(
                    sample.truth, prediction
                ),
                "reading_order_score": reading_order_score(
                    sample.truth, prediction
                ),
                "duration_ms": duration_ms,
                "warning": warning,
                "suspicions": suspicions,
                "error": error,
                "metadata": metadata,
            }
        )

    overall = _aggregate_rows(results)
    return {
        "dataset": str(root),
        "requested_engine": engine,
        "preprocess": preprocess,
        **overall,
        "total_duration_ms": sum(
            row["duration_ms"] for row in results
        ),
        "groups": _group_report(results),
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
    print(f"Failures: {report['failure_count']}")
    print(
        "Mean CER: "
        + ("n/a" if mean is None else f"{mean:.4f}")
    )
    print(
        "Mean compact CER: "
        + ("n/a" if compact is None else f"{compact:.4f}")
    )
    order_score = report["mean_reading_order_score"]
    print(
        "Mean reading-order score: "
        + ("n/a" if order_score is None else f"{order_score:.4f}")
    )
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
