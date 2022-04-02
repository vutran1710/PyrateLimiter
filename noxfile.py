import nox
from nox_poetry import session

# Reuse virtualenv created by poetry instead of creating new ones
nox.options.reuse_existing_virtualenvs = True


@session(python=False)
def lint(session) -> None:
    session.run("pre-commit", "run", "--all-files")


@session(python=False)
def cover(session) -> None:
    session.run("coverage", "run", "-m", "--source=pyrate_limiter", "pytest", "tests", "--maxfail=1")
    session.run("coverage", "report", "-m")
    session.run("coverage", "xml")


@session(python=False)
def test(session) -> None:
    session.run(
        "pytest",
        "--maxfail=1",
        "--verbose",
        "-s",
        "--fulltrace",
    )
