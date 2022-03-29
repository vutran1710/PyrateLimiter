from subprocess import check_call


def format():
    check_call(["black", "pyrate_limiter/"])
    check_call(["black", "tests/"])
    check_call(["isort", "."])


def lint() -> None:
    check_call(["pre-commit", "run", "--all-files"])


def cover() -> None:
    check_call(["radon", "mi", "-x", "A", "."])
    check_call(["coverage", "run", "-m", "--source=pyrate_limiter", "pytest", "tests", "--maxfail=1"])
    check_call(["coverage", "report", "-m"])
    check_call(["coverage", "xml"])


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
