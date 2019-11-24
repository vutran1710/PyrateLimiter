from subprocess import check_call


def lint() -> None:
    check_call(["flake8", "snaky_bucket/"])
    check_call(["pylint", "snaky_bucket/"])
    check_call(["autopep8", "snaky_bucket/*.py"])


def test() -> None:
    check_call(["pytest", "tests/", "--verbose", "-s", "--cov=snaky_bucket"])
