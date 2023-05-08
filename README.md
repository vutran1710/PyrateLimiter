<img align="left" width="95" height="120" src="docs/_static/logo.png">

# PyrateLimiter
The request rate limiter using Leaky-bucket algorithm.

Full project documentation can be found at [pyratelimiter.readthedocs.io](https://pyratelimiter.readthedocs.io).

[![PyPI version](https://badge.fury.io/py/pyrate-limiter.svg)](https://badge.fury.io/py/pyrate-limiter)
[![PyPI - Python Versions](https://img.shields.io/pypi/pyversions/pyrate-limiter)](https://pypi.org/project/pyrate-limiter)
[![codecov](https://codecov.io/gh/vutran1710/PyrateLimiter/branch/master/graph/badge.svg?token=E0Q0YBSINS)](https://codecov.io/gh/vutran1710/PyrateLimiter)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/vutran1710/PyrateLimiter/graphs/commit-activity)
[![PyPI license](https://img.shields.io/pypi/l/ansicolortags.svg)](https://pypi.python.org/pypi/pyrate-limiter/)

<br>

## Contents
- [PyrateLimiter](#pyratelimiter)
  - [Contents](#contents)
  - [Features](#features)
  - [Installation](#installation)
  - [Basic usage](#basic-usage)
    - [Defining rate limits](#defining-rate-limits)
    - [Applying rate limits](#applying-rate-limits)
    - [Identities](#identities)
  - [Handling exceeded limits](#handling-exceeded-limits)
    - [Bucket analogy](#bucket-analogy)
    - [Rate limit exceptions](#rate-limit-exceptions)
    - [Rate limit delays](#rate-limit-delays)
  - [Additional usage options](#additional-usage-options)
    - [Decorator](#decorator)
    - [Contextmanager](#contextmanager)
    - [Async decorator/contextmanager](#async-decoratorcontextmanager)
  - [Backends](#backends)
    - [Memory](#memory)
    - [SQLite](#sqlite)
    - [Redis](#redis)
    - [Custom backends](#custom-backends)
  - [Additional features](#additional-features)
    - [Time sources](#time-sources)
  - [Examples](#examples)

## Features
* Tracks any number of rate limits and intervals you want to define
* Independently tracks rate limits for multiple services or resources
* Handles exceeded rate limits by either raising errors or adding delays
* Several usage options including a normal function call, a decorator, or a contextmanager
* Async support
* Includes optional SQLite and Redis backends, which can be used to persist limit tracking across
  multiple threads, processes, or application restarts

## Installation
Install using pip:
```
pip install pyrate-limiter
```

Or using conda:
```
conda install --channel conda-forge pyrate-limiter
```
