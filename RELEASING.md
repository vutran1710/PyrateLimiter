# Release Workflow

This document describes how to publish a new version of PyrateLimiter to PyPI.

## Versioning

PyrateLimiter uses [uv-dynamic-versioning](https://github.com/ninoseki/uv-dynamic-versioning) to derive the package version from **git tags**. There is no hardcoded version in `pyproject.toml` — the version is determined at build time from the most recent `v*` tag.

## Prerequisites

- Push access to the `master` branch
- [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) configured on PyPI for this repository (one-time setup — see below)

### One-time PyPI Trusted Publisher setup

1. Go to https://pypi.org/manage/project/pyrate-limiter/settings/publishing/
2. Add a new GitHub trusted publisher:
   - **Owner:** `vutran1710`
   - **Repository:** `PyrateLimiter`
   - **Workflow name:** `build_test.yml`
   - **Environment:** *(leave blank)*

## Release steps

### 1. Ensure `master` is up to date

```shell
git checkout master
git pull origin master
```

### 2. Review changes since last release

```shell
git log $(git describe --tags --abbrev=0)..HEAD --oneline
```

### 3. Create and push a version tag

Follow [Semantic Versioning](https://semver.org/):
- **Patch** (v4.0.x): bug fixes, test improvements
- **Minor** (v4.x.0): new features, backwards-compatible changes
- **Major** (vX.0.0): breaking API changes

```shell
git tag v<VERSION>
git push origin v<VERSION>
```

### 4. CI takes over

Pushing a `v*` tag triggers the [build_test.yml](.github/workflows/build_test.yml) workflow which:

1. **smoke** — lints and runs smoke tests
2. **check-linux** — runs full test suite on Python 3.10, 3.14, 3.14t with Redis and Postgres services; builds the wheel on the latest Python
3. **check-others** — runs tests on macOS and PyPy
4. **publish** — downloads the built artifacts, publishes to PyPI via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/), **and** creates a GitHub Release for the tag with auto-generated notes and the build artifacts attached.

### 5. (Optional) Verify / edit the GitHub Release

CI creates the GitHub Release and attaches the `dist/*` artifacts automatically.
Edit the auto-generated notes if you want a curated summary:

```shell
gh release view v<VERSION>
gh release edit v<VERSION> --notes-file <path>   # optional
```

### 6. Update CHANGELOG.md

Add an entry for the new version in `CHANGELOG.md` following the existing format.

## Verifying the release

```shell
# Check PyPI
pip install pyrate-limiter==<VERSION>

# Check GitHub
gh release view v<VERSION>
```
