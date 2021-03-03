from subprocess import check_call


def lint() -> None:
    check_call(["flake8", "pyrate_limiter/"])
    check_call(["pylint", "pyrate_limiter/", "--rcfile=setup.cfg"])
    check_call(["autopep8", "pyrate_limiter/*.py"])


def cover() -> None:
    check_call(["coverage", "run", "-m", "--source=pyrate_limiter", "pytest", "tests", "--maxfail=1"])
    check_call(["coverage", "report", "-m"])
    check_call(["radon", "mi", "-x", "A", "."])
    check_call(["coveralls"])


def test() -> None:
    check_call(
        [
            "pytest",
            "tests",
            "--maxfail=1",
            "--verbose",
            "-s",
            "--fulltrace",
        ]
    )
    check_call(["radon", "mi", "-x", "A", "."])
