from glob import glob

import nox
from nox_poetry import session

# Reuse virtualenv created by poetry instead of creating new ones
nox.options.reuse_existing_virtualenvs = True

# Manually select serial tests. TODO: Add a "serial" marker
PYTEST_MP_ARGS = ["--verbose", "--maxfail=1", "tests/test_multiprocessing.py"]
COVERAGE_APPEND_ARGS = ["--cov=pyrate_limiter", "--cov-report="]

PYTEST_MP2_ARGS = ["--verbose", "--maxfail=1", "-m", "mpbucket and monotonic",
                   "--ignore=tests/test_multiprocessing.py"]
COVERAGE_APPEND2_ARGS = ["--cov=pyrate_limiter", "--cov-append", "--cov-report="]

# Reduce # of cores to 3: one less than GHA runner's cores: timing tests are sensitive to high load
PYTEST_ARGS = ["--verbose", "--maxfail=1", "-m", "not mpbucket", "--numprocesses=3",
               "--ignore=tests/test_multiprocessing.py"]
COVERAGE_REPORT_ARGS = ["--cov=pyrate_limiter",
                        "--cov-append",
                        "--cov-report=term",
                        "--cov-report=xml",
                        "--cov-report=html"]


def get_examples():
    return [f for f in glob("examples/*.py") if f != "examples/httpx_ratelimiter.py"]


@session(python=False)
def lint(session) -> None:
    session.run("pre-commit", "run", "--all-files")


@session(python=False)
def cover(session) -> None:
    """Run tests and generate coverage reports in both terminal output and XML (for Codecov)"""

    # Serial Files
    session.run("pytest", *PYTEST_MP_ARGS, *COVERAGE_APPEND_ARGS)

    # Serial Markers
    session.run("pytest", *PYTEST_MP2_ARGS, *COVERAGE_APPEND2_ARGS)

    # Everything else - concurrent
    session.run("pytest", *PYTEST_ARGS, *COVERAGE_REPORT_ARGS, "tests", *get_examples())


@session(python=False)
def test(session) -> None:
    session.run("pytest", *PYTEST_MP_ARGS)
    session.run("pytest", *PYTEST_MP2_ARGS)
    session.run("pytest", *PYTEST_ARGS, "tests", *get_examples())


@session(python=False)
def docs(session):
    """Build Sphinx documentation"""
    session.run("sphinx-build", "docs", "docs/_build/html", "-j", "auto")
