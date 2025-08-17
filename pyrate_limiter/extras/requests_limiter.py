import logging
from typing import Any, Union

from requests import Response, Session

from pyrate_limiter import Limiter

logger = logging.getLogger(__name__)


class RateLimitedRequestsSession(Session):
    """
    A requests.Session that enforces a rate limit via a provided Limiter.

    The limiter's ``try_acquire(name)`` is called before every outbound request.
    """

    def __init__(self, limiter: "Limiter", name: str = __name__, **_: Any) -> None:
        """
        Initialize the rate-limited session.

        Args:
            limiter: Object exposing ``try_acquire(str) -> None`` that blocks/raises when over limit.
            name: Token/key used by the limiter to bucket this session's requests.
            ``**_``: Ignored; accepted for API compatibility.
        """
        super().__init__()
        self._limiter = limiter
        self._name = name

    def request(self, method: Union[str, bytes], url: Union[str, bytes], *args: Any, **kwargs: Any) -> Response:
        """
        Perform an HTTP request after acquiring from the limiter.

        Args:
            method: HTTP method (e.g., "GET", "POST").
            url: Request URL.
            ``*args``, ``**kwargs``: Passed through to ``requests.Session.request``.

        Returns:
            :class:`requests.Response` returned by the underlying session.
        """
        self._limiter.try_acquire(self._name)
        return super().request(method, url, *args, **kwargs)

    def close(self) -> None:
        """
        Close the underlying HTTP adapters and release resources.
        """
        return super().close()
