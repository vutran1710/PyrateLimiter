import nox
from nox_poetry import session

# Reuse virtualenv created by poetry instead of creating new ones
nox.options.reuse_existing_virtualenvs = True


@session(python=False)
def lint(session) -> None:
    session.run("pre-commit", "run", "--all-files")


@session(python=False)
def cover(session) -> None:
    """Run tests and generate coverage reports in both terminal output and XML (for Codecov)"""
    session.run("pytest", "--maxfail=1", "--numprocesses=auto", "--cov", "--cov-report=term", "--cov-report=xml")


@session(python=False)
def test(session) -> None:
    session.run(
        "pytest",
        "--maxfail=1",
        "--verbose",
        "-s",
        "--fulltrace",
        "--numprocesses=auto",
    )
