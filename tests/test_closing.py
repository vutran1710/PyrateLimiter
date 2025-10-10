import pytest
from .conftest import DEFAULT_RATES
from pyrate_limiter import Limiter

@pytest.mark.asyncio
async def test_multiple_bucket_closes(
    create_bucket,
):
    # Makes sure no exceptions even if close is called multiple times
    
    with await create_bucket(DEFAULT_RATES) as bucket:
        bucket.close()
    bucket.close()


@pytest.mark.asyncio
async def test_multiple_bucket_closes_limiter(
    create_bucket,
):
    # Makes sure no exceptions even if close is called multiple times
    
    with await create_bucket(DEFAULT_RATES) as bucket:
        with Limiter(bucket) as limiter:
            limiter.close()
        bucket.close()
    bucket.close()
