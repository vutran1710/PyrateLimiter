"""Compare weighted RedisBucket put latency between two source checkouts.

Example:
    uv run --group all python benchmarks/compare_redis_weighted_put.py \
        --baseline /tmp/pyrate-master \
        --candidate /tmp/pyrate-candidate \
        --redis-url redis://localhost:6379
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter_ns
from typing import Any

DEFAULT_WEIGHTS = [1, 10, 100, 1000, 5000]


def percentile(values: list[int], fraction: float) -> float:
    """Return a nearest-rank percentile in microseconds."""
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index] / 1_000


def checkout_commit(checkout: Path) -> str:
    """Return the checkout commit when it is a Git worktree."""
    try:
        return subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def iterations_for_weight(args: argparse.Namespace, weight: int) -> int:
    """Keep each round useful without making large weights prohibitively slow."""
    estimated = args.target_members_per_round // weight
    return max(args.min_iterations, min(args.max_iterations, estimated))


def run_worker(args: argparse.Namespace) -> None:
    """Measure one checkout and print raw nanosecond samples as JSON."""
    sys.path.insert(0, str(args.checkout))

    from redis import Redis

    from pyrate_limiter import Rate, RateItem, RedisBucket

    redis = Redis.from_url(args.redis_url)
    redis.ping()
    key = f"benchmark:redis-weight:{args.label}:{args.weight}:{os.getpid()}"
    bucket = RedisBucket.init([Rate(args.weight, 60_000)], redis, key)
    samples_ns: list[int] = []

    try:
        for index in range(args.warmup + args.iterations):
            redis.delete(key)
            item = RateItem("benchmark", bucket.now(), weight=args.weight)
            started = perf_counter_ns()
            accepted = bucket.put(item)
            elapsed = perf_counter_ns() - started
            if not accepted:
                raise RuntimeError("benchmark put was rejected")
            if index >= args.warmup:
                samples_ns.append(elapsed)
    finally:
        redis.delete(key)
        redis.close()

    print(json.dumps({"label": args.label, "weight": args.weight, "samples_ns": samples_ns}))


def run_block(
    args: argparse.Namespace,
    label: str,
    checkout: Path,
    weight: int,
    iterations: int,
) -> list[int]:
    """Run an isolated worker so imports from the two checkouts cannot mix."""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--checkout",
        str(checkout),
        "--label",
        label,
        "--weight",
        str(weight),
        "--iterations",
        str(iterations),
        "--warmup",
        str(args.warmup),
        "--redis-url",
        args.redis_url,
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)["samples_ns"]


def render_markdown(results: dict[str, Any]) -> str:
    """Render a compact table suitable for a pull request comment."""
    lines = [
        f"Baseline: `{results['baseline_commit'][:12]}`; candidate: `{results['candidate_commit'][:12]}`; "
        f"Redis: `{results['redis_version']}`; rounds: {results['rounds']}.",
        "",
        "| Weight | Samples/version | Baseline median | Candidate median | Median reduction | Baseline p95 | Candidate p95 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in results["rows"]:
        lines.append(
            "| {weight} | {samples_per_version} | {baseline_median_us:.1f} us | "
            "{candidate_median_us:.1f} us | {median_reduction_pct:+.1f}% | "
            "{baseline_p95_us:.1f} us | {candidate_p95_us:.1f} us |".format(**row)
        )
    return "\n".join(lines)


def compare(args: argparse.Namespace) -> None:
    """Alternate both checkouts across rounds and summarize their samples."""
    from redis import Redis

    checkouts = {
        "baseline": args.baseline.resolve(),
        "candidate": args.candidate.resolve(),
    }
    samples: dict[tuple[str, int], list[int]] = {
        (label, weight): [] for label in checkouts for weight in args.weights
    }

    redis = Redis.from_url(args.redis_url)
    redis_version = str(redis.info("server")["redis_version"])
    redis.close()

    for round_index in range(args.rounds):
        order = ("baseline", "candidate") if round_index % 2 == 0 else ("candidate", "baseline")
        for weight in args.weights:
            iterations = iterations_for_weight(args, weight)
            for label in order:
                samples[(label, weight)].extend(
                    run_block(args, label, checkouts[label], weight, iterations)
                )

    rows = []
    for weight in args.weights:
        baseline = samples[("baseline", weight)]
        candidate = samples[("candidate", weight)]
        baseline_median = statistics.median(baseline) / 1_000
        candidate_median = statistics.median(candidate) / 1_000
        rows.append(
            {
                "weight": weight,
                "samples_per_version": len(baseline),
                "baseline_median_us": baseline_median,
                "candidate_median_us": candidate_median,
                "median_reduction_pct": (1 - candidate_median / baseline_median) * 100,
                "baseline_p95_us": percentile(baseline, 0.95),
                "candidate_p95_us": percentile(candidate, 0.95),
            }
        )

    results = {
        "baseline_commit": checkout_commit(checkouts["baseline"]),
        "candidate_commit": checkout_commit(checkouts["candidate"]),
        "redis_version": redis_version,
        "rounds": args.rounds,
        "rows": rows,
    }
    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2) + "\n")
    print(render_markdown(results))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--redis-url", default=os.getenv("REDIS", "redis://localhost:6379"))
    parser.add_argument("--weights", nargs="+", type=int, default=DEFAULT_WEIGHTS)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--target-members-per-round", type=int, default=120_000)
    parser.add_argument("--min-iterations", type=int, default=40)
    parser.add_argument("--max-iterations", type=int, default=1000)
    parser.add_argument("--json-output", type=Path)

    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--checkout", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--label", help=argparse.SUPPRESS)
    parser.add_argument("--weight", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--iterations", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        required = (args.checkout, args.label, args.weight, args.iterations)
        if any(value is None for value in required):
            parser.error("worker mode requires checkout, label, weight, and iterations")
    elif args.baseline is None or args.candidate is None:
        parser.error("comparison mode requires baseline and candidate checkouts")
    return args


if __name__ == "__main__":
    parsed = parse_args()
    if parsed.worker:
        run_worker(parsed)
    else:
        compare(parsed)
