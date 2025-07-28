import nox
from nox_poetry import session

# Reuse virtualenv created by poetry instead of creating new ones
nox.options.reuse_existing_virtualenvs = True

PYTEST_MP_ARGS = ["--verbose", "--cov=pyrate_limiter", "--maxfail=1", "tests/test_multiprocessing.py"]
PYTEST_MP2_ARGS = ["--verbose", "--cov=pyrate_limiter", "--maxfail=1", "-m", "mpbucket and monotonic",
                   "--ignore=tests/test_multiprocessing.py"]
PYTEST_ARGS = ["--verbose", "--maxfail=1", "-m", "not mpbucket", "--numprocesses=auto",
               "--ignore=tests/test_multiprocessing.py"]
COVERAGE_ARGS = ["--cov=pyrate_limiter", "--cov-append", "--cov-report=term", "--cov-report=xml", "--cov-report=html"]


@session(python=False)
def lint(session) -> None:
    session.run("pre-commit", "run", "--all-files")


@session(python=False)
def cover(session) -> None:
    """Run tests and generate coverage reports in both terminal output and XML (for Codecov)"""

    # Serial Files
    session.run("pytest", *PYTEST_MP_ARGS)

    # Serial Markers
    session.run("pytest", *PYTEST_MP2_ARGS)

    # Everything else - concurrent
    session.run("pytest", *PYTEST_ARGS, *COVERAGE_ARGS)


@session(python=False)
def test(session) -> None:
    session.run("pytest", *PYTEST_MP_ARGS)
    session.run("pytest", *PYTEST_ARGS)


@session(python=False)
def docs(session):
    """Build Sphinx documentation"""
    session.run("sphinx-build", "docs", "docs/_build/html", "-j", "auto")
