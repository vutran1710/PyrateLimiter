import logging
import re
from inspect import isawaitable
from threading import Thread
from time import monotonic, sleep, time

import pytest

from pyrate_limiter import binary_search
from pyrate_limiter import Duration
from pyrate_limiter import Rate
from pyrate_limiter import RateItem
from pyrate_limiter import SQLiteClock
from pyrate_limiter import MonotonicClock
from pyrate_limiter import AbstractClock

from pyrate_limiter import validate_rate_list

from pyrate_limiter.limiter import combined_lock

from multiprocessing import Lock
from threading import RLock

def test_combined_lock_blocking_ok():
    m, r = Lock(), RLock()
    with combined_lock([m, r], blocking=True):
        assert m.acquire(False) is False
    assert m.acquire(False) is True
    m.release()

def test_combined_lock_nonblocking_fails_if_mp_locked():
    m, r = Lock(), RLock()
    m.acquire()
    try:
        with pytest.raises(TimeoutError): 
            with combined_lock([m, r], blocking=False): 
                pass
    finally:
        m.release()

def test_combined_lock_timeout_when_mp_locked():
    m, r = Lock(), RLock()
    m.acquire()
    try:
        with pytest.raises(TimeoutError):
            with combined_lock([m, r], blocking=True, timeout=0.05): 
                pass
    finally:
        m.release()

def test_zero_timeout_behaves_nonblocking():
    m, r = Lock(), RLock()
    m.acquire()
    try:
        with pytest.raises(TimeoutError):
            with combined_lock([m, r], True, timeout=0): pass
    finally:
        m.release()

def test_partial_acquire_rolls_back_on_failure():
    m1, m2 = Lock(), Lock()
    m2.acquire()
    try:
        with pytest.raises(TimeoutError):
            with combined_lock([m1, m2], False): pass
        assert m1.acquire(False) is True  # released after failure
        m1.release()
    finally:
        m2.release()

def test_exception_inside_context_releases_all():
    m, r = Lock(), RLock()
    with pytest.raises(RuntimeError):
        with combined_lock([m, r], True): raise RuntimeError
    assert m.acquire(False) is True; m.release()

def test_reentrant_rlock_ok():
    r = RLock()
    with r:
        with combined_lock([r], True): assert True

def test_single_lock_works():
    m = Lock()
    with combined_lock([m], True): assert True
    assert m.acquire(False) is True; m.release()

def test_float_timeout():
    m, r = Lock(), RLock()
    m.acquire()
    try:
        with pytest.raises(TimeoutError):
            with combined_lock([m, r], True, timeout=0.05): pass
    finally:
        m.release()

def test_nonblocking_when_uncontended():
    m, r = Lock(), RLock()
    with combined_lock([m, r], False): assert True
    assert m.acquire(False) is True; m.release()

def test_order_doesnt_deadlock_when_second_is_locked():
    m1, m2 = Lock(), Lock()
    m2.acquire()
    try:
        with pytest.raises(TimeoutError):
            with combined_lock([m1, m2], True, timeout=0.01): pass
    finally:
        m2.release()


def test_timeout_is_global_budget_across_locks():
    m1, m2 = Lock(), Lock()
    m1.acquire()
    m2.acquire()

    def release_first_lock_later():
        sleep(0.03)
        m1.release()

    releaser = Thread(target=release_first_lock_later)
    releaser.start()
    started = monotonic()

    try:
        with pytest.raises(TimeoutError):
            with combined_lock([m1, m2], True, timeout=0.05):
                pass
    finally:
        releaser.join()
        m2.release()

    elapsed = monotonic() - started
    assert elapsed < 0.08