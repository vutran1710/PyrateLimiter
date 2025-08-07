# Contributing Guide
Here are some basic instructions for local development setup and contributing to the project.

## Setup & Commands
To setup local development, *uv* and *Python 3.9+* are required. Follow instructions at <https://docs.astral.sh/uv/getting-started/installation/> for installing uv.

Then, in the repository directory, run the following to install all optional backend dependencies and dev dependencies:
```shell
$ uv sync --all-groups --all-extras
```

Some shortcuts are included for some common development tasks, using [nox](https://nox.thea.codes):
- Run tests with: `nox -e test`
- To run tests with coverage: `nox -e cover`
- Format & check for lint error: `nox -e lint`
- To run linting for every commit, run: `pre-commit install`

## Documentation
Documentation is generated using [Sphinx](https://www.sphinx-doc.org) and published on readthedocs.io.
To build this documentation locally:
```
nox -e docs
```

## Guideline & Notes
We have GitHub Action CICD to do the checking, testing and publishing work. So, there are few small notes when making Pull Request:
- All existing tests must pass (Of course!)
- Reduction in *Coverage* shall result in failure. (below 98% is not accepted)
- When you are making bug fixes, or adding more features, remember to bump the version number in **pyproject.toml**. The number should follow *semantic-versioning* rules

## TODO
Planned features:
* A rate limit may reset on a fixed schedule, eg: every first-day of a month
* Sometimes, we may need to apply specific rate-limiting strategies based on schedules/region or some other metrics. It
  requires the capability to switch the strategies instantly without re-deploying the whole service.
  * Reference: https://www.keycdn.com/support/rate-limiting#types-of-rate-limits
