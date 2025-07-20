import logging
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
from dataclasses import dataclass
from functools import partial
from time import perf_counter
from typing import Callable
from typing import cast
from typing import Literal
from typing import Optional

from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import SQLiteBucket
from pyrate_limiter import SQLiteClock

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    label: str
    requests_per_second: int
    test_duration_seconds: int
    duration: float
    num_requests: int
    percent_from_expected_duration: float


def create_sqlite_limiter(rate: Rate, use_fileLock: bool, max_delay: int):
    bucket = SQLiteBucket.init_from_file([rate], db_path="pyrate_limiter.sqlite", use_file_lock=use_fileLock)

    # retry_until_max_delay=True
    if use_fileLock:
        kwargs = dict(clock=SQLiteClock(bucket))
    else:
        kwargs = {}

    return Limiter(bucket, raise_when_fail=False, max_delay=max_delay, **kwargs)


def create_rate_limiter_factory(
    requests_per_second: int,
    max_delay_seconds: int,
    backend: Literal["default", "sqlite", "sqlite_filelock"],
) -> Callable[[], Limiter]:
    """Returns a callable, so it can be used with multiprocessing"""
    max_delay = max_delay_seconds * 1000  # should never wait for more than 60 seconds
    rate = Rate(requests_per_second, Duration.SECOND)

    if backend == "default":
        return partial(Limiter, rate, raise_when_fail=False, max_delay=max_delay)
    elif backend == "sqlite":
        return partial(
            create_sqlite_limiter, rate, use_fileLock=False, max_delay=max_delay
        )
    elif backend == "sqlite_filelock":
        return partial(
            create_sqlite_limiter, rate, use_fileLock=True, max_delay=max_delay
        )
    else:
        raise ValueError(f"Unexpected backend option: {backend}")


SHARED_LIMITER: Optional[Limiter] = None


def task():
    assert SHARED_LIMITER is not None, "Limiter not initialized"

    try:
        acquired = SHARED_LIMITER.try_acquire("task")

        if not acquired:
            raise ValueError("Failed to acquire")
    except Exception as e:
        logger.exception(e)


def limiter_init(limiter_factory: Callable[[], Limiter]):
    global SHARED_LIMITER
    SHARED_LIMITER = limiter_factory()


def test_rate_limiter(
    limiter_factory: Optional[Callable[[], Limiter]],
    num_requests: int,
    use_process_pool: bool,
):
    start = perf_counter()

    if use_process_pool:
        logger.info("Using ProcessPoolExecutor")
        with ProcessPoolExecutor(
            initializer=partial(limiter_init, limiter_factory) if limiter_factory is not None else None
        ) as executor:
            futures = [executor.submit(task) for _ in range(num_requests)]
            wait(futures)
    else:
        with ThreadPoolExecutor() as executor:
            limiter = limiter_factory() if limiter_factory is not None else None
            global SHARED_LIMITER
            SHARED_LIMITER = limiter

            futures = [executor.submit(task) for _ in range(num_requests)]
            wait(futures)

    for f in futures:
        try:
            f.result()
        except Exception as e:
            print(f"Task raised: {e}")

    end = perf_counter()

    return end - start


def run_test_limiter(
    limiter: Callable | None,
    label: str,
    requests_per_second: int,
    test_duration_seconds: int,
    use_process_pool: bool = False,
):
    num_requests = (
        test_duration_seconds * requests_per_second
    )  # should finish in around 20 seconds

    duration = test_rate_limiter(
        limiter, num_requests=num_requests, use_process_pool=use_process_pool
    )

    percent_from_expected_duration = (
        abs(duration) - test_duration_seconds
    ) / test_duration_seconds

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

    requests_per_second_list = [10, 100, 1000, 2500, 5000, 7500]

    test_duration_seconds = 10

    test_results = []

    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)-8s %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for backend in ["default", "sqlite", "sqlite_filelock"]:
        backend = cast(Literal["default", "sqlite", "sqlite_filelock"], backend)
        for requests_per_second in requests_per_second_list:
            logger.info(f"Testing with {backend=}, {requests_per_second=}")
            limiter = create_rate_limiter_factory(
                requests_per_second, max_delay_seconds=60, backend=backend
            )
            result = run_test_limiter(
                limiter=limiter,
                label="Threads: " + backend,
                requests_per_second=requests_per_second,
                test_duration_seconds=test_duration_seconds,
            )
            test_results.append(result)

    logger.info("Testing Multiprocessing")
    for backend in ["sqlite_filelock"]:
        backend = cast(Literal["default", "sqlite", "sqlite_filelock"], backend)

        for requests_per_second in requests_per_second_list:
            logger.info(f"Testing with {backend=}, {requests_per_second=}")

            limiter_factory = create_rate_limiter_factory(
                requests_per_second, max_delay_seconds=60, backend=backend
            )
            result = run_test_limiter(
                limiter=limiter_factory,
                label="Processes: " + backend,
                requests_per_second=requests_per_second,
                test_duration_seconds=test_duration_seconds,
                use_process_pool=True,
            )
            test_results.append(result)

    results_df = pd.DataFrame(test_results).sort_values(by="requests_per_second")
    results_df["requests_per_second"] = results_df["requests_per_second"].astype(str)
    fig = px.line(
        results_df, x="requests_per_second", y="duration", color="label", markers=True
    )
    fig.write_html("chart.html")

    logger.info("Output written to chart.html")
