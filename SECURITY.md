# Vulnerability Report: SQL Injection in `SQLiteBucket` Leading to Rate-Limit Bypass

## Summary

I identified a SQL injection vulnerability in the SQLite backend of PyrateLimiter.

The issue is in `pyrate_limiter/buckets/sqlite_bucket.py`, where untrusted `RateItem.name` data is interpolated directly into an SQL `INSERT` statement without parameter binding. In applications that pass attacker-controlled input into `Limiter.try_acquire(name=...)` while using `SQLiteBucket`, an attacker can manipulate inserted row values and bypass effective rate limiting.

In my local verification, a crafted `name` payload was able to alter the inserted timestamp so that the request was accepted but no longer counted inside the active rate-limit window. As a result, subsequent requests were also accepted when they should have been rejected.

## Severity

I consider this issue **High severity** in realistic deployments where the `name` parameter is derived from user-controlled data such as IP addresses, API keys, user IDs, route keys, or request metadata.

## Affected Component

- Project: `PyrateLimiter`
- Component: `pyrate_limiter/buckets/sqlite_bucket.py`
- Vulnerable function: `SQLiteBucket.put()`

## Technical Details

The vulnerable code constructs SQL like this:

```python
items = ", ".join([f"('{name}', {item.timestamp})" for name in [item.name] * item.weight])
query = (Queries.PUT_ITEM.format(table=self.table)) % items
self.conn.execute(query).close()
```

Because `item.name` is inserted directly into the SQL string, a malicious value can break out of the intended string literal and modify the inserted values.

## Impact

Depending on how the library is integrated, the vulnerability may allow:

- Rate-limit bypass
- Corruption of bucket records
- Integrity issues in limiter state
- Application-level abuse due to loss of request throttling

The primary practical impact I confirmed is **rate-limit bypass** against the SQLite backend.

## Proof of Concept

The following minimal example demonstrates the issue:

```python
from pyrate_limiter import Rate, Duration, RateItem
from pyrate_limiter.buckets.sqlite_bucket import SQLiteBucket

bucket = SQLiteBucket.init_from_file(
    [Rate(1, Duration.SECOND)],
    table="demo_audit",
    db_path=":memory:",
    create_new_table=True,
)

print(bucket.put(RateItem("a', 0) --", bucket.now())))
print(bucket.put(RateItem("normal", bucket.now())))
print(bucket.count())
print(bucket.conn.execute("SELECT name, item_timestamp FROM 'demo_audit'").fetchall())
```

Observed behavior during my local verification:

- The first malicious request was accepted.
- The inserted row used a modified timestamp (`0`) instead of the current timestamp.
- A second normal request was also accepted even though the configured limit was `1 request / second`.

This shows the attacker can make accepted requests fall outside the intended accounting window.

## Root Cause

The root cause is unsafe SQL string construction with attacker-influenced data.

This should be fixed by:

- Using parameterized SQL for inserted values
- Avoiding direct string interpolation for user-controlled content
- Reviewing SQL construction for table names and identifiers separately

## Suggested Remediation

I recommend replacing dynamic value interpolation with bound parameters. For example, the insert path should use parameterized `executemany()` or equivalent prepared statements instead of building raw SQL tuples from strings.

It would also be useful to add a regression test that:

- Uses a malicious `name` payload
- Verifies the payload is stored as plain data
- Verifies rate-limit accounting is still enforced correctly

## Disclosure Request

I am reporting this issue privately to support coordinated disclosure.

If you confirm the issue, please:

1. Create a private GitHub security advisory for this vulnerability.
2. Request a CVE through GitHub Security Advisories.
3. Credit me as the original reporter in the advisory and public disclosure.

## Credit Request

Please include the following credit in the advisory or release note:

> Reported by [BAOZEXUAN / YMsora]

If you prefer, I can also provide a final public credit string in the exact format you want to use.

## Notes

- I have a working local reproduction.
- I have not publicly disclosed this issue.
- I am available to validate a fix or review a patch before publication.
