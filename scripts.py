from subprocess import check_call


def lint() -> None:
    check_call(["flake8", "pyrate_limiter/"])
    check_call(["pylint", "pyrate_limiter/", "--rcfile=setup.cfg"])
    check_call(["autopep8", "pyrate_limiter/*.py"])


def test() -> None:
    check_call([
        "pytest",
        "tests",
        "--maxfail=1",
        "--verbose",
        "-s",
    # "--fulltrace",
        "--cov-report",
        "html",
        "--cov=pyrate_limiter"
    ])
    # check_call(["pytest", "tests/", "--verbose", "-s", "--cov=pyrate_limiter"])
