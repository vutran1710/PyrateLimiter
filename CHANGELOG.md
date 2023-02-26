# Change Log
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/)
and this project adheres to [Semantic Versioning](http://semver.org/).

## [2.10.0] - 2023-02-26
### Updates
* Add change log to sdist
* Improve test coverage
* Force check some bucket-keyword arguments

## [2.9.1] - 2023-02-26
### Fixed
* Fix unit test to make test results stable
* Fix remaining-time calculation using exact 3 decimals only
* Increase test intesity to ensure correctness

## [2.8.5] - TBD
### Fixed
* Fix SQLite OperationalError when getting more items than SQLite variable limit

## [2.8.4] - 2022-11-23
### Fixed
* Build both `wheel` and `sdist` on publish

## [2.8.3] - 2022-10-17
### Added
* Add option to expire redis key when using RedisBucket

## [2.8.2] - 2022-09-24
### Removed
* Python 3.6 support

## [2.8.1] - 2022-04-11
### Added
* Add Sphinx config
* Add documentation site: https://pyrate-limiter.readthedocs.io
* Add some missing type hints
* Add package metadata to indicate PEP-561 compliance

## [2.8.0] - 2022-04-10
### Added
* Add `flush()` method to all bucket classes

## [2.7.0] - 2022-04-06
### Added
* Add `FileLockSQliteBucket` for a SQLite backend with file-based locking
* Add optional backend dependencies to package metadata

## [2.6.3] - 2022-04-05
### Fixed
* Make SQLite bucket thread-safe and multiprocess-safe

## [2.6.2] - 2022-03-30
### Fixed
* Remove development scripts from package published on PyPI

### Added
* Add `nox` to run development scripts

## [2.6.1] - 2022-03-30
### Updated
* Replace all formatting/linting tools with *pre-commit*

## [2.6.0] - 2021-12-08
### Added
* Add `SQliteBucket` to persist rate limit data in a SQLite database

## [2.5.0] - 2021-12-08
### Added
* Custom time source

## [2.4.6] - 2021-09-30
* Add `RedisClusterBucket` to support using `PyrateLimiter` with `redis-py-cluster`
* Update README, add Table of Content

## [2.3.6] - 2021-09-23
* Run CI tests for all supported python versions
* Fix issue with deployments on Travis CI

## [2.3.5] - 2021-09-22
### Added
* Use `time.monotonic()` instead of `time.time()`
* Support for floating point rate-limiting delays (more granular than 1 second)

## [2.3.4] - 2021-06-01
### Fixed
* Bucket group initialization

## [2.3.3] - 2021-05-08
### Added
* Support for python 3.6

## [2.3.2] - 2021-05-06
### Fixed
* Incorrect type hint

## [2.3.1] - 2021-04-26
### Added
* LICENSE file to be included in PyPI package

### Fixed
* Incorrect delay time when using using `Limiter.ratelimit()` with `delay=True`

## [2.3.0] - 2021-03-01
### Added
* Support for using `Limiter.ratelimit()` as a contextmanager or async contextmanager
* Separate `LimitContextDecorator` class to handle `Limiter.ratelimit()` behavior
* Package published on conda-forge

## [2.2.2] - 2021-03-03
### Changed
* Internal: Reduce cognitive complexity

## [2.2.1] - 2021-03-02
### Fixed
* Incorrect check log against time-window

## [2.2.0] - 2021-02-26
### Added
* `Limiter.ratelimit()` method, an async-compatible decorator that optionally adds rate-limiting delays

## [2.1.0] - 2021-02-21

## [2.0.3] - 2020-06-01

## [2.0.2] - 2020-06-01

## [2.0.1] - 2020-06-01

## [2.0.0] - 2019-12-29

## [1.1.0] - 2019-12-17
### Removed
- Code duplication

### Added
- Thread lock for Bucket's state modification in case of Multi-threading
- Html Cover Report

### Fixed
- LocalBucket's default init value being mutated
- Typos. A lot of friggin' typos.
