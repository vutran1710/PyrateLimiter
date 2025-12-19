# ruff: noqa: G004
import logging
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import dataclass
from functools import partial
from time import perf_counter
from typing import Callable, Literal, cast

from pyrate_limiter import Duration, Limiter, MultiprocessBucket, Rate, limiter_factory

logger = logging.getLogger(__name__)

BUFFER_MS: int = 1  # reduce the buffer to improve measurement
TEST_DURATION_SEC: int = 1  # time per test
PREFILL: bool = True


@dataclass
class TestResult:
    label: str
    requests_per_second: int
    test_duration_seconds: int
    duration: float
    num_requests: int
    percent_from_expected_duration: float


def create_mp_limiter(bucket: MultiprocessBucket):
    limiter = Limiter(bucket, buffer_ms=BUFFER_MS)

    return limiter


def create_rate_limiter_factory(
    requests_per_second: int,
    backend: Literal["default", "sqlite", "sqlite_filelock", "mp_limiter"],
) -> Callable[[], Limiter]:
    """Returns a callable, so it can be used with multiprocessing"""
    rate = Rate(requests_per_second, Duration.SECOND)

    if backend == "default":
        limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=requests_per_second, duration=Duration.SECOND, buffer_ms=BUFFER_MS)
        return lambda: limiter
    elif backend == "sqlite":
        limiter = limiter_factory.create_sqlite_limiter(
            rate_per_duration=requests_per_second, use_file_lock=False, buffer_ms=BUFFER_MS, db_path="pyrate_limiter.sqlite"
        )
        return lambda: limiter
    elif backend == "sqlite_filelock":
        return partial(
            limiter_factory.create_sqlite_limiter,
            rate_per_duration=requests_per_second,
            duration=Duration.SECOND,
            use_file_lock=True,
            buffer_ms=BUFFER_MS,
            db_path="pyrate_limiter.sqlite",
        )
    elif backend == "mp_limiter":
        bucket = MultiprocessBucket.init([rate])
        return partial(create_mp_limiter, bucket=bucket)
    else:
        raise ValueError(f"Unexpected backend option: {backend}")


def task():
    assert limiter_factory.LIMITER is not None, "Limiter not initialized"

    try:
        limiter_factory.LIMITER.try_acquire("task")
    except Exception as e:
        logger.exception(e)


def limiter_init(limiter_creator: Callable[[], Limiter]):
    limiter_factory.LIMITER = limiter_creator()


def test_rate_limiter(
    limiter_creator: Callable[[], Limiter],
    num_requests: int,
    use_process_pool: bool,
):
    start = perf_counter()

    if use_process_pool:
        logger.info("Using ProcessPoolExecutor")
        with ProcessPoolExecutor(initializer=partial(limiter_init, limiter_creator) if limiter_creator is not None else None) as executor:
            if PREFILL:
                # Pre-load the buckets, after processes created
                limiter = limiter_creator()
                [limiter.try_acquire("task") for i in range(requests_per_second)]

            futures = [executor.submit(task) for _ in range(num_requests)]
            wait(futures)
    else:
        with ThreadPoolExecutor() as executor:
            if PREFILL:
                # Pre-load the buckets, after threads created
                limiter = limiter_creator()
                [limiter.try_acquire("task") for i in range(requests_per_second)]

            limiter = limiter_creator()
            limiter_factory.LIMITER = limiter

            futures = [executor.submit(task) for _ in range(num_requests)]
            wait(futures)

    for f in futures:
        try:
            f.result()
        except Exception as e:
            logger.exception(f"Task raised: {e}")

    end = perf_counter()

    return end - start


def run_test_limiter(
    limiter_creator: Callable,
    label: str,
    requests_per_second: int,
    test_duration_seconds: int,
    use_process_pool: bool = False,
):
    num_requests = test_duration_seconds * requests_per_second  # should finish in around 20 seconds

    duration = test_rate_limiter(limiter_creator=limiter_creator, num_requests=num_requests, use_process_pool=use_process_pool)

    percent_from_expected_duration = (abs(duration) - test_duration_seconds) / test_duration_seconds

    return TestResult(
        label=label,
        requests_per_second=requests_per_second,
        test_duration_seconds=test_duration_seconds,
        duration=duration,
        num_requests=num_requests,
        percent_from_expected_duration=percent_from_expected_duration,
    )


if __name__ == "__main__":
    import pandas as pd
    import plotly.express as px

    requests_per_second_list = [10, 100, 1000, 2500, 5000]

    test_duration_seconds = TEST_DURATION_SEC

    test_results = []

    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)-8s %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for backend in ["default", "sqlite", "mp_limiter"]:
        backend = cast(Literal["default", "sqlite", "sqlite_filelock", "mp_limiter"], backend)
        for requests_per_second in requests_per_second_list:
            logger.info(f"Testing with {backend=}, {requests_per_second=}")
            limiter_creator = create_rate_limiter_factory(requests_per_second, backend=backend)

            result = run_test_limiter(
                limiter_creator=limiter_creator,
                label="Threads: " + backend,
                requests_per_second=requests_per_second,
                test_duration_seconds=test_duration_seconds,
            )
            test_results.append(result)

    logger.info("Testing Multiprocessing")
    for backend in ["sqlite_filelock", "mp_limiter"]:
        backend = cast(Literal["default", "sqlite", "sqlite_filelock", "mp_limiter"], backend)

        for requests_per_second in requests_per_second_list:
            logger.info(f"Testing with {backend=}, {requests_per_second=}")

            limiter_creator = create_rate_limiter_factory(requests_per_second, backend=backend)
            result = run_test_limiter(
                limiter_creator=limiter_creator,
                label="Processes: " + backend,
                requests_per_second=requests_per_second,
                test_duration_seconds=test_duration_seconds,
                use_process_pool=True,
            )
            test_results.append(result)

    results_df = pd.DataFrame(test_results).sort_values(by="requests_per_second")
    results_df["requests_per_second"] = results_df["requests_per_second"].astype(str)
    fig = px.line(results_df, x="requests_per_second", y="duration", color="label", markers=True)
    fig.write_html("chart.html")

    logger.info("Output written to chart.html")
