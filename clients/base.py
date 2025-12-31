"""Base HTTP client with rate limiting and retry logic."""

import time
import random
from functools import wraps
from typing import Any, Optional
import httpx

from errors import NetworkError, RateLimitError


class BaseClient:
    """Base HTTP client with rate limiting and exponential backoff retry."""

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        rate_limit: int = 10,  # requests per second
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
        verbose: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        self.verbose = verbose

        # Rate limiting state
        self._request_times: list[float] = []

        # HTTP client
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Lazy-initialize HTTP client."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self):
        """Close HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _check_rate_limit(self):
        """Enforce rate limiting using sliding window."""
        now = time.time()

        # Remove requests older than 1 second
        self._request_times = [t for t in self._request_times if now - t < 1.0]

        # If at limit, sleep until oldest request expires
        if len(self._request_times) >= self.rate_limit:
            sleep_time = 1.0 - (now - self._request_times[0])
            if sleep_time > 0:
                if self.verbose:
                    print(f"Rate limit: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)

        # Record this request
        self._request_times.append(time.time())

    def _request(
        self,
        method: str,
        path: str,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> httpx.Response:
        """Make HTTP request with rate limiting and retry."""
        url = f"{self.base_url}{path}"
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                self._check_rate_limit()

                response = self.client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json,
                )

                # Check for rate limit response
                if response.status_code == 429:
                    raise RateLimitError(f"Rate limited: {response.text}")

                return response

            except (httpx.NetworkError, httpx.TimeoutException) as e:
                last_exception = NetworkError(f"Network error: {e}")

            except RateLimitError as e:
                last_exception = e

            # Retry with exponential backoff
            if attempt < self.max_retries:
                delay = self.retry_delay * (self.retry_backoff ** attempt)
                delay += random.uniform(0, 1)  # Jitter

                if self.verbose:
                    print(f"Attempt {attempt + 1} failed, retrying in {delay:.2f}s")

                time.sleep(delay)
            else:
                raise last_exception

        raise last_exception

    def get(
        self,
        path: str,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        """GET request."""
        return self._request("GET", path, headers=headers, params=params)

    def post(
        self,
        path: str,
        headers: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> httpx.Response:
        """POST request."""
        return self._request("POST", path, headers=headers, json=json)

    def delete(
        self,
        path: str,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        """DELETE request."""
        return self._request("DELETE", path, headers=headers, params=params)
