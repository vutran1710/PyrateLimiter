import nox
from nox_poetry import session

# Reuse virtualenv created by poetry instead of creating new ones
nox.options.reuse_existing_virtualenvs = True

PYTEST_ARGS = ["--verbose", "--maxfail=1", "--numprocesses=8"]
COVERAGE_ARGS = ["--cov", "--cov-report=term", "--cov-report=xml", "--cov-report=html"]


@session(python=False)
def lint(session) -> None:
    session.run("pre-commit", "run", "--all-files")


@session(python=False)
def cover(session) -> None:
    """Run tests and generate coverage reports in both terminal output and XML (for Codecov)"""
    session.run("pytest", *PYTEST_ARGS, *COVERAGE_ARGS)


@session(python=False)
def test(session) -> None:
    session.run("pytest", *PYTEST_ARGS)


@session(python=False)
def docs(session):
    """Build Sphinx documentation"""
    session.run("sphinx-build", "docs", "docs/_build/html", "-j", "auto")
