"""Compare RedisBucket pressure between two source checkouts.

The benchmark fills and rotates realistic Redis buckets while a second client
samples PING latency. Run it against a dedicated Redis instance because CPU and
command statistics are server-wide.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
from pathlib import Path
from threading import Event, Thread
from time import perf_counter_ns, sleep
from typing import Any

DEFAULT_ROUNDS = 5
DEFAULT_STEPS = 100
DEFAULT_STEADY_CYCLES = 2
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


def percentile_us(values: list[int], fraction: float) -> float:
    """Return a nearest-rank percentile in microseconds."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index] / 1_000


def checkout_commit(checkout: Path) -> str:
    """Return the checkout commit when it is a Git worktree."""
    return subprocess.check_output(  # noqa: S603
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],  # noqa: S607
        text=True,
    ).strip()


def read_first(path: Path, prefix: str) -> str:
    """Read the first matching value from a Linux proc file."""
    if not path.exists():
        return "unknown"
    for line in path.read_text().splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[-1].strip()
    return "unknown"


def runner_resources() -> dict[str, Any]:
    """Describe the machine so benchmark results are reproducible."""
    affinity = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else set()
    return {
        "os": platform.platform(),
        "runner_image": os.getenv("ImageOS", "local"),
        "runner_image_version": os.getenv("ImageVersion", "unknown"),
        "python": platform.python_version(),
        "cpu_model": read_first(Path("/proc/cpuinfo"), "model name"),
        "host_cpu_count": os.cpu_count() or 0,
        "benchmark_cpu_count": len(affinity) if affinity else os.cpu_count() or 0,
        "benchmark_cpu_set": ",".join(str(cpu) for cpu in sorted(affinity)) or "unknown",
        "memory_total": read_first(Path("/proc/meminfo"), "MemTotal"),
        "redis_cpu_limit": os.getenv("REDIS_CPU_LIMIT", "unlimited"),
        "redis_memory_limit": os.getenv("REDIS_MEMORY_LIMIT", "unlimited"),
    }


def split_weight(cap: int, steps: int) -> list[int]:
    """Split a cap into positive, near-equal acquisition weights."""
    count = min(cap, steps)
    base, remainder = divmod(cap, count)
    return [base + (index < remainder) for index in range(count)]


def event_timestamps(now: int, interval: int, count: int) -> list[int]:
    """Distribute events over one complete sliding window."""
    if count == 1:
        return [now]
    start = now - interval + 1
    return [start + ((interval - 1) * index // (count - 1)) for index in range(count)]


def server_snapshot(redis: Any) -> dict[str, float]:
    """Capture the two Redis counters used by the report."""
    cpu = redis.info("cpu")
    commands = redis.info("commandstats")
    evalsha = commands.get("cmdstat_evalsha", {})
    return {
        "cpu_seconds": float(cpu.get("used_cpu_sys", 0)) + float(cpu.get("used_cpu_user", 0)),
        "evalsha_usec": float(evalsha.get("usec", 0)),
    }


def start_ping_sampler(redis_url: str, interval_ms: float) -> tuple[Event, Thread, list[int], list[str]]:
    """Sample unrelated Redis latency from an independent connection."""
    ready = Event()
    stop = Event()
    samples: list[int] = []
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
                samples.append(perf_counter_ns() - started)
                sleep(interval_ms / 1_000)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            ready.set()
        finally:
            client.close()

    thread = Thread(target=sample, daemon=True)
    thread.start()
    if not ready.wait(timeout=5) or errors:
        raise RuntimeError(errors[0] if errors else "PING sampler did not start")
    return stop, thread, samples, errors


def fill_bucket(bucket: Any, item_type: Any, cap: int, interval: int, steps: int) -> tuple[list[int], list[int]]:
    """Fill a bucket to its cap and return event timestamps and weights."""
    weights = split_weight(cap, steps)
    timestamps = event_timestamps(bucket.now(), interval, len(weights))
    for index, (timestamp, weight) in enumerate(zip(timestamps, weights, strict=True)):
        if not bucket.put(item_type(f"fill-{index}", timestamp, weight=weight)):
            raise RuntimeError("bucket prefill was rejected")
    return timestamps, weights


def run_workload(
    args: argparse.Namespace,
    bucket: Any,
    item_type: Any,
    steady_state: tuple[list[int], list[int]] | None,
) -> list[int]:
    """Execute growth or steady replacement and return operation latency."""
    interval = WINDOWS_MS[args.window]
    if steady_state is None:
        weights = split_weight(args.cap, args.steps)
        timestamps = event_timestamps(bucket.now(), interval, len(weights))
    else:
        timestamps, weights = steady_state
    samples: list[int] = []
    cycles = args.steady_cycles if args.workload == "steady" else 1
    for cycle in range(cycles):
        for index, weight in enumerate(weights):
            timestamp = timestamps[index]
            if args.workload == "steady":
                timestamp += interval + 1
                timestamps[index] = timestamp
            started = perf_counter_ns()
            if args.workload == "steady":
                bucket.leak(timestamp)
            accepted = bucket.put(item_type(f"{args.workload}-{cycle}-{index}", timestamp, weight=weight))
            samples.append(perf_counter_ns() - started)
            if not accepted:
                raise RuntimeError("benchmark operation was rejected")
    return samples


def run_worker(args: argparse.Namespace) -> None:
    """Measure one checkout and print raw samples as JSON."""
    sys.path.insert(0, str(args.checkout))

    from redis import Redis

    from pyrate_limiter import Rate, RateItem, RedisBucket

    redis = Redis.from_url(args.redis_url)
    key = f"benchmark:redis-pressure:{args.label}:{args.workload}:{args.window}:{os.getpid()}"
    bucket = RedisBucket.init([Rate(args.cap, WINDOWS_MS[args.window])], redis, key)
    redis.delete(key)

    try:
        steady_state = None
        if args.workload == "steady":
            steady_state = fill_bucket(bucket, RateItem, args.cap, WINDOWS_MS[args.window], args.steps)
        before = server_snapshot(redis)
        stop, thread, ping_samples, ping_errors = start_ping_sampler(args.redis_url, args.ping_interval_ms)
        try:
            operation_samples = run_workload(args, bucket, RateItem, steady_state)
        finally:
            stop.set()
            thread.join(timeout=5)
        if thread.is_alive() or ping_errors:
            raise RuntimeError(ping_errors[0] if ping_errors else "PING sampler did not stop")
        after = server_snapshot(redis)
        payload = {
            "operation_samples": operation_samples,
            "ping_samples": ping_samples,
            "memory_bytes": int(redis.memory_usage(key) or 0),
            "cardinality": int(redis.zcard(key)),
            "cpu_seconds": max(0.0, after["cpu_seconds"] - before["cpu_seconds"]),
            "evalsha_usec": max(0.0, after["evalsha_usec"] - before["evalsha_usec"]),
        }
    finally:
        redis.delete(key)
        redis.close()

    print(json.dumps(payload))  # noqa: T201


def run_worker_process(
    args: argparse.Namespace,
    label: str,
    checkout: Path,
    workload: str,
    window: str,
    cap: int,
) -> dict[str, Any]:
    """Run an isolated checkout so its imports cannot mix."""
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
        "--rounds",
        "1",
        "--steps",
        str(args.steps),
        "--steady-cycles",
        str(args.steady_cycles),
        "--ping-interval-ms",
        str(args.ping_interval_ms),
        "--redis-url",
        args.redis_url,
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    return json.loads(completed.stdout)


def summarize(runs: list[dict[str, Any]]) -> dict[str, float]:
    """Aggregate repeated worker runs."""
    operations = [value for run in runs for value in run["operation_samples"]]
    pings = [value for run in runs for value in run["ping_samples"]]
    return {
        "operation_p95_us": percentile_us(operations, 0.95),
        "ping_p99_us": percentile_us(pings, 0.99),
        "ping_max_us": max(pings, default=0) / 1_000,
        "ping_samples": len(pings),
        "memory_bytes": statistics.median(run["memory_bytes"] for run in runs),
        "cardinality": statistics.median(run["cardinality"] for run in runs),
        "cpu_seconds": sum(run["cpu_seconds"] for run in runs),
        "evalsha_usec": sum(run["evalsha_usec"] for run in runs),
    }


def reduction(baseline: float, candidate: float) -> float:
    """Return positive percentages when the candidate uses less."""
    return 0.0 if baseline == 0 else (1 - candidate / baseline) * 100


def render_markdown(results: dict[str, Any]) -> str:
    """Render runner resources and pressure results."""
    resources = results["resources"]
    lines = [
        "## Redis pressure benchmark",
        "",
        f"Baseline {results['baseline_commit'][:12]}; candidate {results['candidate_commit'][:12]}; Redis {results['redis_version']}.",
        "",
        "### Environment",
        "",
        "| Resource | Value |",
        "| --- | --- |",
        f"| Runner | {resources['runner_image']} {resources['runner_image_version']} |",
        f"| OS | {resources['os']} |",
        f"| Host CPU | {resources['cpu_model']} ({resources['host_cpu_count']} logical CPUs) |",
        f"| Benchmark CPU | {resources['benchmark_cpu_count']} logical CPU; affinity {resources['benchmark_cpu_set']} |",
        f"| Redis container | {resources['redis_cpu_limit']} CPU; {resources['redis_memory_limit']} memory |",
        f"| Host RAM | {resources['memory_total']} |",
        f"| Python | {resources['python']} |",
        f"| Redis maxmemory | {results['redis_maxmemory']} bytes ({results['redis_policy']}) |",
        f"| Configuration | {results['rounds']} rounds, {results['steps']} steps, {results['steady_cycles']} steady cycles |",
        "",
    ]
    for workload in WORKLOADS:
        lines.extend(
            [
                f"### {workload.title()}",
                "",
                "| Window | Cap | Op p95 B/C | Reduction | PING samples B/C | PING p99 B/C | PING max B/C | CPU reduction | EVALSHA reduction | Memory | ZCARD |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for scenario in results["scenarios"]:
            baseline = scenario[workload]["baseline"]
            candidate = scenario[workload]["candidate"]
            lines.append(
                "| {window} | {cap:,} | {op_b:.1f}/{op_c:.1f} us | {op_r:+.1f}% | "
                "{ping_n_b:.0f}/{ping_n_c:.0f} | {ping_b:.1f}/{ping_c:.1f} us | "
                "{ping_max_b:.1f}/{ping_max_c:.1f} us | {cpu_r:+.1f}% | {eval_r:+.1f}% | "
                "{memory:.1f} KiB | {cardinality:,.0f} |".format(
                    window=scenario["window"].title(),
                    cap=scenario["cap"],
                    op_b=baseline["operation_p95_us"],
                    op_c=candidate["operation_p95_us"],
                    op_r=reduction(baseline["operation_p95_us"], candidate["operation_p95_us"]),
                    ping_n_b=baseline["ping_samples"],
                    ping_n_c=candidate["ping_samples"],
                    ping_b=baseline["ping_p99_us"],
                    ping_c=candidate["ping_p99_us"],
                    ping_max_b=baseline["ping_max_us"],
                    ping_max_c=candidate["ping_max_us"],
                    cpu_r=reduction(baseline["cpu_seconds"], candidate["cpu_seconds"]),
                    eval_r=reduction(baseline["evalsha_usec"], candidate["evalsha_usec"]),
                    memory=candidate["memory_bytes"] / 1_024,
                    cardinality=candidate["cardinality"],
                )
            )
        lines.append("")
    return "\n".join(lines)


def compare(args: argparse.Namespace) -> None:
    """Compare both checkouts across all configured scenarios."""
    from redis import Redis

    checkouts = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    scenarios = args.scenario or DEFAULT_SCENARIOS
    raw: dict[tuple[str, str, str], list[dict[str, Any]]] = {
        (label, workload, window): [] for label in checkouts for workload in WORKLOADS for window, _ in scenarios
    }
    for round_index in range(args.rounds):
        order = ("baseline", "candidate") if round_index % 2 == 0 else ("candidate", "baseline")
        for window, cap in scenarios:
            for workload in WORKLOADS:
                for label in order:
                    raw[(label, workload, window)].append(run_worker_process(args, label, checkouts[label], workload, window, cap))

    redis = Redis.from_url(args.redis_url)
    server = redis.info("server")
    memory = redis.info("memory")
    policy = redis.config_get("maxmemory-policy")
    redis.close()
    results = {
        "baseline_commit": checkout_commit(checkouts["baseline"]),
        "candidate_commit": checkout_commit(checkouts["candidate"]),
        "redis_version": server["redis_version"],
        "redis_maxmemory": memory.get("maxmemory", 0),
        "redis_policy": policy.get("maxmemory-policy", "unknown"),
        "resources": runner_resources(),
        "rounds": args.rounds,
        "steps": args.steps,
        "steady_cycles": args.steady_cycles,
        "scenarios": [
            {
                "window": window,
                "cap": cap,
                **{workload: {label: summarize(raw[(label, workload, window)]) for label in checkouts} for workload in WORKLOADS},
            }
            for window, cap in scenarios
        ],
    }
    markdown = render_markdown(results)
    if args.json_output:
        args.json_output.write_text(json.dumps(results, indent=2) + "\n")
    if args.markdown_output:
        args.markdown_output.write_text(markdown + "\n")
    print(markdown)  # noqa: T201


def parse_scenario(value: str) -> tuple[str, int]:
    """Parse WINDOW=CAP command-line values."""
    try:
        window, cap_text = value.split("=", 1)
        cap = int(cap_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scenario must use WINDOW=CAP") from exc
    if window not in WINDOWS_MS or cap < 1:
        raise argparse.ArgumentTypeError("scenario must use a known WINDOW and positive CAP")
    return window, cap


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--redis-url", default=os.getenv("REDIS", "redis://localhost:6379"))
    parser.add_argument("--scenario", action="append", type=parse_scenario)
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--steady-cycles", type=int, default=DEFAULT_STEADY_CYCLES)
    parser.add_argument("--ping-interval-ms", type=float, default=1.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--checkout", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--label", help=argparse.SUPPRESS)
    parser.add_argument("--workload", choices=WORKLOADS, help=argparse.SUPPRESS)
    parser.add_argument("--window", choices=WINDOWS_MS, help=argparse.SUPPRESS)
    parser.add_argument("--cap", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.rounds < 1 or args.steps < 1 or args.steady_cycles < 1 or args.ping_interval_ms < 0:
        parser.error("rounds, steps, and cycles must be positive; ping interval cannot be negative")
    if args.worker:
        if any(value is None for value in (args.checkout, args.label, args.workload, args.window, args.cap)):
            parser.error("worker mode requires checkout, label, workload, window, and cap")
    elif args.baseline is None or args.candidate is None:
        parser.error("comparison mode requires baseline and candidate checkouts")
    return args


if __name__ == "__main__":
    parsed = parse_args()
    run_worker(parsed) if parsed.worker else compare(parsed)
