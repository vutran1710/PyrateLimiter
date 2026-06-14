"""Compare RedisBucket pressure between two source checkouts.

Measures bucket growth and steady replacement while an independent connection
samples PING latency. Use a dedicated Redis instance because CPU, network, and
command statistics are server-wide.

Example:
    uv run --group all python benchmarks/compare_redis_pressure.py \
        --baseline /tmp/pyrate-v4.3.0 \
        --candidate /tmp/pyrate-v4.4.0 \
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
from threading import Event, Thread
from time import perf_counter, perf_counter_ns, sleep
from typing import Any

DEFAULT_ROUNDS = 5
DEFAULT_SCENARIOS = [
    ("second", 60),
    ("minute", 1_000),
    ("hour", 5_000),
    ("day", 50_000),
    ("month", 100_000),
]
WINDOWS_MS = {
    "second": 1_000,
    "minute": 60_000,
    "hour": 3_600_000,
    "day": 86_400_000,
    "month": 2_592_000_000,
}
WORKLOADS = ("growth", "steady")


def percentile_ns(values: list[int], fraction: float) -> float:
    """Return a nearest-rank percentile in microseconds."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index] / 1_000


def checkout_commit(checkout: Path) -> str:
    """Return the checkout commit when it is a Git worktree."""
    try:
        return subprocess.check_output(  # noqa: S603
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],  # noqa: S607
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def split_weight(cap: int, steps: int) -> list[int]:
    """Split a cap into positive, near-equal acquisition weights."""
    count = min(cap, steps)
    base, remainder = divmod(cap, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def event_timestamps(now: int, interval: int, count: int) -> list[int]:
    """Distribute events over one complete sliding window."""
    start = now - interval + 1
    if count == 1:
        return [now]
    return [start + ((interval - 1) * index // (count - 1)) for index in range(count)]


def command_value(info: dict[str, Any], command: str, field: str) -> float:
    """Read one numeric INFO commandstats field."""
    return float(info.get(f"cmdstat_{command}", {}).get(field, 0))


def server_snapshot(redis: Any) -> dict[str, float]:
    """Capture server-wide counters used to calculate workload deltas."""
    cpu = redis.info("cpu")
    stats = redis.info("stats")
    commands = redis.info("commandstats")
    return {
        "cpu_seconds": float(cpu.get("used_cpu_sys", 0)) + float(cpu.get("used_cpu_user", 0)),
        "net_input_bytes": float(stats.get("total_net_input_bytes", 0)),
        "net_output_bytes": float(stats.get("total_net_output_bytes", 0)),
        "evalsha_calls": command_value(commands, "evalsha", "calls"),
        "evalsha_usec": command_value(commands, "evalsha", "usec"),
        "zrem_calls": command_value(commands, "zremrangebyscore", "calls"),
        "zrem_usec": command_value(commands, "zremrangebyscore", "usec"),
    }


def subtract_snapshots(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """Return non-negative server counter deltas."""
    return {key: max(0.0, after[key] - value) for key, value in before.items()}


def start_ping_sampler(redis_url: str, interval_ms: float) -> tuple[Event, Thread, list[int], list[str]]:
    """Continuously sample PING latency from an independent connection."""
    ready = Event()
    stop = Event()
    samples_ns: list[int] = []
    errors: list[str] = []

    def sample() -> None:
        from redis import Redis

        client = Redis.from_url(redis_url)
        try:
            client.ping()
            ready.set()
            while not stop.is_set():
                started = perf_counter_ns()
                client.ping()
                samples_ns.append(perf_counter_ns() - started)
                if interval_ms:
                    sleep(interval_ms / 1_000)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            ready.set()
        finally:
            client.close()

    thread = Thread(target=sample, name="redis-pressure-ping", daemon=True)
    thread.start()
    if not ready.wait(timeout=5):
        raise RuntimeError("PING sampler did not connect within five seconds")
    if errors:
        raise RuntimeError(f"PING sampler failed: {errors[0]}")
    return stop, thread, samples_ns, errors


def put_timed(bucket: Any, item: Any) -> int:
    """Put one item and return elapsed nanoseconds."""
    started = perf_counter_ns()
    accepted = bucket.put(item)
    elapsed = perf_counter_ns() - started
    if not accepted:
        raise RuntimeError("benchmark put was rejected")
    return elapsed


def fill_bucket(bucket: Any, item_type: Any, cap: int, interval: int, steps: int) -> tuple[list[int], list[int]]:
    """Fill a bucket and return event timestamps and their weights."""
    weights = split_weight(cap, steps)
    timestamps = event_timestamps(bucket.now(), interval, len(weights))
    for index, (timestamp, weight) in enumerate(zip(timestamps, weights, strict=False)):
        accepted = bucket.put(item_type(f"prefill-{index}", timestamp, weight=weight))
        if not accepted:
            raise RuntimeError("benchmark prefill was rejected")
    return timestamps, weights


def growth_workload(
    bucket: Any,
    item_type: Any,
    redis: Any,
    key: str,
    cap: int,
    interval: int,
    steps: int,
) -> tuple[list[int], int, list[dict[str, int]]]:
    """Fill an empty bucket and sample pressure at occupancy checkpoints."""
    weights = split_weight(cap, steps)
    timestamps = event_timestamps(bucket.now(), interval, len(weights))
    thresholds = [25, 50, 75, 100]
    checkpoints: list[dict[str, int]] = []
    latencies_ns: list[int] = []
    inserted = 0

    for index, (timestamp, weight) in enumerate(zip(timestamps, weights, strict=False)):
        item = item_type(f"growth-{index}", timestamp, weight=weight)
        latencies_ns.append(put_timed(bucket, item))
        inserted += weight
        while thresholds and inserted * 100 >= cap * thresholds[0]:
            checkpoints.append(
                {
                    "fill_pct": thresholds.pop(0),
                    "cardinality": int(redis.zcard(key)),
                    "memory_bytes": int(redis.memory_usage(key) or 0),
                }
            )

    return latencies_ns, inserted, checkpoints


def steady_workload(
    bucket: Any,
    item_type: Any,
    redis: Any,
    key: str,
    timestamps: list[int],
    weights: list[int],
    interval: int,
    cycles: int,
) -> tuple[list[int], int, list[dict[str, int]]]:
    """Replace expired acquisitions while keeping bucket occupancy stable."""
    latencies_ns: list[int] = []
    replaced = 0

    for cycle in range(cycles):
        for index, weight in enumerate(weights):
            timestamps[index] += interval + 1
            timestamp = timestamps[index]
            started = perf_counter_ns()
            bucket.leak(timestamp)
            accepted = bucket.put(item_type(f"steady-{cycle}-{index}", timestamp, weight=weight))
            latencies_ns.append(perf_counter_ns() - started)
            if not accepted:
                raise RuntimeError("steady-state replacement was rejected")
            replaced += weight

    checkpoints = [
        {
            "fill_pct": 100,
            "cardinality": int(redis.zcard(key)),
            "memory_bytes": int(redis.memory_usage(key) or 0),
        }
    ]
    return latencies_ns, replaced, checkpoints


def run_worker(args: argparse.Namespace) -> None:
    """Run one isolated checkout/workload and emit raw measurements."""
    sys.path.insert(0, str(args.checkout))

    from redis import Redis

    from pyrate_limiter import Rate, RateItem, RedisBucket

    redis = Redis.from_url(args.redis_url)
    redis.ping()
    interval = WINDOWS_MS[args.window]
    key = f"benchmark:redis-pressure:{args.label}:{args.workload}:{args.window}:{os.getpid()}"
    bucket = RedisBucket.init([Rate(args.cap, interval)], redis, key)
    redis.delete(key)

    try:
        steady_state: tuple[list[int], list[int]] | None = None
        if args.workload == "steady":
            steady_state = fill_bucket(bucket, RateItem, args.cap, interval, args.steps)

        before = server_snapshot(redis)
        stop, thread, ping_samples_ns, ping_errors = start_ping_sampler(args.redis_url, args.ping_interval_ms)
        try:
            started = perf_counter()
            if args.workload == "growth":
                operation_samples_ns, units, checkpoints = growth_workload(bucket, RateItem, redis, key, args.cap, interval, args.steps)
            else:
                assert steady_state is not None
                operation_samples_ns, units, checkpoints = steady_workload(
                    bucket,
                    RateItem,
                    redis,
                    key,
                    steady_state[0],
                    steady_state[1],
                    interval,
                    args.steady_cycles,
                )
            elapsed_seconds = perf_counter() - started
        finally:
            stop.set()
            thread.join(timeout=5)

        if thread.is_alive():
            raise RuntimeError("PING sampler did not stop")
        if ping_errors:
            raise RuntimeError(f"PING sampler failed: {ping_errors[0]}")
        after = server_snapshot(redis)
        payload = {
            "label": args.label,
            "workload": args.workload,
            "window": args.window,
            "cap": args.cap,
            "operation_samples_ns": operation_samples_ns,
            "ping_samples_ns": ping_samples_ns,
            "elapsed_seconds": elapsed_seconds,
            "units": units,
            "operations": len(operation_samples_ns),
            "final_cardinality": int(redis.zcard(key)),
            "final_memory_bytes": int(redis.memory_usage(key) or 0),
            "checkpoints": checkpoints,
            "telemetry": subtract_snapshots(before, after),
        }
    finally:
        redis.delete(key)
        redis.close()

    print(json.dumps(payload))  # noqa: T201


def run_block(
    args: argparse.Namespace,
    label: str,
    checkout: Path,
    workload: str,
    window: str,
    cap: int,
) -> dict[str, Any]:
    """Run one worker subprocess so checkout imports cannot mix."""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--checkout",
        str(checkout),
        "--label",
        label,
        "--workload",
        workload,
        "--window",
        window,
        "--cap",
        str(cap),
        "--steps",
        str(args.steps),
        "--steady-cycles",
        str(args.steady_cycles),
        "--ping-interval-ms",
        str(args.ping_interval_ms),
        "--redis-url",
        args.redis_url,
    ]
    completed = subprocess.run(  # noqa: S603
        command, check=True, capture_output=True, text=True
    )
    return json.loads(completed.stdout)


def median_checkpoint(runs: list[dict[str, Any]], fill_pct: int, field: str) -> float:
    """Return the median checkpoint measurement across rounds."""
    values = [checkpoint[field] for run in runs for checkpoint in run["checkpoints"] if checkpoint["fill_pct"] == fill_pct]
    return float(statistics.median(values)) if values else 0.0


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate raw worker runs into client and Redis pressure metrics."""
    operation_samples = [sample for run in runs for sample in run["operation_samples_ns"]]
    ping_samples = [sample for run in runs for sample in run["ping_samples_ns"]]
    telemetry = {key: sum(float(run["telemetry"][key]) for run in runs) for key in runs[0]["telemetry"]}
    elapsed_seconds = sum(float(run["elapsed_seconds"]) for run in runs)
    units = sum(int(run["units"]) for run in runs)
    operations = sum(int(run["operations"]) for run in runs)
    return {
        "rounds": len(runs),
        "operations": operations,
        "units": units,
        "elapsed_seconds": elapsed_seconds,
        "units_per_second": units / elapsed_seconds,
        "operation_p50_us": percentile_ns(operation_samples, 0.50),
        "operation_p95_us": percentile_ns(operation_samples, 0.95),
        "operation_p99_us": percentile_ns(operation_samples, 0.99),
        "ping_samples": len(ping_samples),
        "ping_p50_us": percentile_ns(ping_samples, 0.50),
        "ping_p95_us": percentile_ns(ping_samples, 0.95),
        "ping_p99_us": percentile_ns(ping_samples, 0.99),
        "ping_max_us": max(ping_samples, default=0) / 1_000,
        "final_cardinality": statistics.median(int(run["final_cardinality"]) for run in runs),
        "final_memory_bytes": statistics.median(int(run["final_memory_bytes"]) for run in runs),
        "memory_at_25_pct": median_checkpoint(runs, 25, "memory_bytes"),
        "memory_at_50_pct": median_checkpoint(runs, 50, "memory_bytes"),
        "memory_at_75_pct": median_checkpoint(runs, 75, "memory_bytes"),
        "memory_at_100_pct": median_checkpoint(runs, 100, "memory_bytes"),
        "telemetry": telemetry,
    }


def reduction_pct(baseline: float, candidate: float) -> float:
    """Return positive percentages when the candidate uses less time or CPU."""
    if baseline == 0:
        return 0.0
    return (1 - candidate / baseline) * 100


def render_markdown(results: dict[str, Any]) -> str:
    """Render compact pressure tables suitable for a pull request comment."""
    lines = [
        f"Baseline: {results['baseline_commit'][:12]}; candidate: "
        f"{results['candidate_commit'][:12]}; Redis: {results['redis_version']}; "
        f"rounds: {results['rounds']}.",
        "",
        "Server-wide CPU/network deltas require a dedicated Redis instance.",
        "",
    ]
    for workload in results["workloads"]:
        lines.extend(
            [
                f"### {workload.title()}",
                "",
                "| Window | Cap | Baseline op p95 | Candidate op p95 | Op reduction | PING samples B/C | Baseline PING p99/max | Candidate PING p99/max | CPU reduction | EVALSHA reduction | Memory | ZCARD |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for scenario in results["scenarios"]:
            baseline = scenario[workload]["baseline"]
            candidate = scenario[workload]["candidate"]
            lines.append(
                "| {window} | {cap:,} | {baseline_p95:.1f} us | {candidate_p95:.1f} us | "
                "{op_reduction:+.1f}% | {baseline_ping_samples:,}/{candidate_ping_samples:,} | {baseline_ping_p99:.1f}/{baseline_ping_max:.1f} us | "
                "{candidate_ping_p99:.1f}/{candidate_ping_max:.1f} us | {cpu_reduction:+.1f}% | "
                "{evalsha_reduction:+.1f}% | {memory_kib:.1f} KiB | {cardinality:,.0f} |".format(
                    window=scenario["window"].title(),
                    cap=scenario["cap"],
                    baseline_p95=baseline["operation_p95_us"],
                    candidate_p95=candidate["operation_p95_us"],
                    op_reduction=reduction_pct(baseline["operation_p95_us"], candidate["operation_p95_us"]),
                    baseline_ping_samples=baseline["ping_samples"],
                    candidate_ping_samples=candidate["ping_samples"],
                    baseline_ping_p99=baseline["ping_p99_us"],
                    baseline_ping_max=baseline["ping_max_us"],
                    candidate_ping_p99=candidate["ping_p99_us"],
                    candidate_ping_max=candidate["ping_max_us"],
                    cpu_reduction=reduction_pct(
                        baseline["telemetry"]["cpu_seconds"],
                        candidate["telemetry"]["cpu_seconds"],
                    ),
                    evalsha_reduction=reduction_pct(
                        baseline["telemetry"]["evalsha_usec"],
                        candidate["telemetry"]["evalsha_usec"],
                    ),
                    memory_kib=candidate["final_memory_bytes"] / 1_024,
                    cardinality=candidate["final_cardinality"],
                )
            )
        lines.append("")
    return "\n".join(lines)


def compare(args: argparse.Namespace) -> None:
    """Alternate checkouts across rounds and aggregate pressure measurements."""
    from redis import Redis

    checkouts = {
        "baseline": args.baseline.resolve(),
        "candidate": args.candidate.resolve(),
    }
    scenarios = args.scenario or DEFAULT_SCENARIOS
    raw: dict[tuple[str, str, str], list[dict[str, Any]]] = {
        (label, workload, window): [] for label in checkouts for workload in args.workloads for window, _ in scenarios
    }

    redis = Redis.from_url(args.redis_url)
    redis_version = str(redis.info("server")["redis_version"])
    redis.close()

    for round_index in range(args.rounds):
        order = ("baseline", "candidate") if round_index % 2 == 0 else ("candidate", "baseline")
        for window, cap in scenarios:
            for workload in args.workloads:
                for label in order:
                    raw[(label, workload, window)].append(
                        run_block(
                            args,
                            label,
                            checkouts[label],
                            workload,
                            window,
                            cap,
                        )
                    )

    scenario_results = []
    for window, cap in scenarios:
        workloads = {workload: {label: summarize_runs(raw[(label, workload, window)]) for label in checkouts} for workload in args.workloads}
        scenario_results.append({"window": window, "cap": cap, **workloads})

    results = {
        "baseline_commit": checkout_commit(checkouts["baseline"]),
        "candidate_commit": checkout_commit(checkouts["candidate"]),
        "redis_version": redis_version,
        "rounds": args.rounds,
        "workloads": args.workloads,
        "steps": args.steps,
        "steady_cycles": args.steady_cycles,
        "ping_interval_ms": args.ping_interval_ms,
        "scenarios": scenario_results,
    }
    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2) + "\n")
    print(render_markdown(results))  # noqa: T201


def parse_scenario(value: str) -> tuple[str, int]:
    """Parse WINDOW=CAP command-line values."""
    try:
        window, cap_text = value.split("=", 1)
        cap = int(cap_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scenario must use WINDOW=CAP") from exc
    if window not in WINDOWS_MS:
        raise argparse.ArgumentTypeError(f"unknown window {window!r}; choose from {', '.join(WINDOWS_MS)}")
    if cap < 1:
        raise argparse.ArgumentTypeError("scenario cap must be positive")
    return window, cap


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--redis-url", default=os.getenv("REDIS", "redis://localhost:6379"))
    parser.add_argument(
        "--scenario",
        action="append",
        type=parse_scenario,
        help="repeatable WINDOW=CAP; defaults to second=60 through month=100000",
    )
    parser.add_argument("--workloads", nargs="+", choices=WORKLOADS, default=list(WORKLOADS))
    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help="repeat every checkout/workload/scenario (default: %(default)s)",
    )
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--steady-cycles", type=int, default=2)
    parser.add_argument("--ping-interval-ms", type=float, default=1.0)
    parser.add_argument("--json-output", type=Path)

    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--checkout", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--label", help=argparse.SUPPRESS)
    parser.add_argument("--workload", choices=WORKLOADS, help=argparse.SUPPRESS)
    parser.add_argument("--window", choices=WINDOWS_MS, help=argparse.SUPPRESS)
    parser.add_argument("--cap", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    for option in ("rounds", "steps", "steady_cycles"):
        if getattr(args, option) < 1:
            parser.error(f"--{option.replace('_', '-')} must be at least 1")
    if args.ping_interval_ms < 0:
        parser.error("--ping-interval-ms cannot be negative")

    if args.worker:
        required = (
            args.checkout,
            args.label,
            args.workload,
            args.window,
            args.cap,
        )
        if any(value is None for value in required):
            parser.error("worker mode requires checkout, label, workload, window, and cap")
    elif args.baseline is None or args.candidate is None:
        parser.error("comparison mode requires baseline and candidate checkouts")
    return args


if __name__ == "__main__":
    parsed = parse_args()
    if parsed.worker:
        run_worker(parsed)
    else:
        compare(parsed)
