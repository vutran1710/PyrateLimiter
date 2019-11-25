from subprocess import check_call


def lint() -> None:
    check_call(["flake8", "pyrate_limiter/"])
    check_call(["pylint", "pyrate_limiter/"])
    check_call(["autopep8", "pyrate_limiter/*.py"])


def test() -> None:
    check_call(["pytest", "tests/", "--verbose", "-s", "--cov=pyrate_limiter"])


def engine_test() -> None:
    check_call([
        "pytest", "tests/test_redis_bucket.py", "--verbose", "-s", "-x",
        "--cov=pyrate_limiter"
    ])
