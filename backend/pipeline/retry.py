"""
Retry and Rate Limiting Utilities.

Provides:
  - Exponential backoff retry for API calls
  - Rate limiting to avoid quota issues
  - Circuit breaker for failing services
"""

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, TypeVar

from rich.console import Console

console = Console()

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True  # Add randomness to delay
    
    # Which exceptions to retry on
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        # API-specific errors added by providers
    )
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt (0-indexed)."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            # Add +/- 25% jitter
            jitter_range = delay * 0.25
            delay = delay + random.uniform(-jitter_range, jitter_range)
        
        return max(0.1, delay)


# Default retry config
DEFAULT_RETRY = RetryConfig()


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    config: RetryConfig | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
    **kwargs: Any,
) -> Any:
    """
    Execute an async function with retry logic.
    
    Args:
        func: The async function to call
        *args: Positional arguments to pass to func
        config: Retry configuration (uses defaults if not provided)
        on_retry: Optional callback called before each retry (attempt, exception)
        **kwargs: Keyword arguments to pass to func
        
    Returns:
        The result of func
        
    Raises:
        The last exception if all retries fail
    """
    config = config or DEFAULT_RETRY
    last_exception: Exception | None = None
    
    for attempt in range(config.max_attempts):
        try:
            return await func(*args, **kwargs)
        except config.retryable_exceptions as e:
            last_exception = e
            
            if attempt < config.max_attempts - 1:
                delay = config.get_delay(attempt)
                
                if on_retry:
                    on_retry(attempt + 1, e)
                else:
                    console.print(
                        f"  [yellow]Retry {attempt + 1}/{config.max_attempts} "
                        f"after {delay:.1f}s: {type(e).__name__}[/yellow]"
                    )
                
                await asyncio.sleep(delay)
            else:
                # Last attempt failed
                raise
        except Exception:
            # Non-retryable exception, raise immediately
            raise
    
    # Should not reach here, but just in case
    if last_exception:
        raise last_exception
    raise RuntimeError("Retry logic error")


def with_retry(config: RetryConfig | None = None):
    """
    Decorator to add retry logic to an async function.
    
    Usage:
        @with_retry(RetryConfig(max_attempts=5))
        async def call_api():
            ...
    """
    config = config or DEFAULT_RETRY
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await retry_async(func, *args, config=config, **kwargs)
        return wrapper
    return decorator


@dataclass
class RateLimiter:
    """
    Token bucket rate limiter.
    
    Limits requests to `requests_per_minute` with burst capability.
    """
    requests_per_minute: float = 60.0
    burst_size: int = 10
    
    # Internal state
    _tokens: float = field(default=0.0, init=False)
    _last_update: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    
    def __post_init__(self):
        self._tokens = float(self.burst_size)
        self._last_update = time.monotonic()
    
    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens from the bucket.
        
        Blocks until tokens are available.
        
        Args:
            tokens: Number of tokens to acquire (default 1)
            
        Returns:
            Time waited in seconds
        """
        async with self._lock:
            waited = 0.0
            
            while True:
                self._refill()
                
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                
                # Calculate wait time for enough tokens
                tokens_needed = tokens - self._tokens
                refill_rate = self.requests_per_minute / 60.0
                wait_time = tokens_needed / refill_rate
                
                # Add small buffer
                wait_time = min(wait_time + 0.1, 5.0)
                
                await asyncio.sleep(wait_time)
                waited += wait_time
    
    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_update
        self._last_update = now
        
        # Add tokens based on time passed
        refill_rate = self.requests_per_minute / 60.0
        self._tokens = min(
            self.burst_size,
            self._tokens + (elapsed * refill_rate)
        )


class RateLimiterRegistry:
    """
    Registry of rate limiters per provider/service.
    
    Allows different rate limits for different API providers.
    """
    
    def __init__(self):
        self._limiters: dict[str, RateLimiter] = {}
        self._default_config = {
            "requests_per_minute": 60.0,
            "burst_size": 10,
        }
    
    def configure(
        self,
        provider: str,
        requests_per_minute: float,
        burst_size: int = 10,
    ):
        """Configure rate limits for a specific provider."""
        self._limiters[provider] = RateLimiter(
            requests_per_minute=requests_per_minute,
            burst_size=burst_size,
        )
    
    def get(self, provider: str) -> RateLimiter:
        """Get or create a rate limiter for a provider."""
        if provider not in self._limiters:
            self._limiters[provider] = RateLimiter(
                requests_per_minute=self._default_config["requests_per_minute"],
                burst_size=self._default_config["burst_size"],
            )
        return self._limiters[provider]
    
    async def acquire(self, provider: str, tokens: int = 1) -> float:
        """Acquire tokens from a provider's rate limiter."""
        limiter = self.get(provider)
        return await limiter.acquire(tokens)


# Global rate limiter registry
_rate_limiters = RateLimiterRegistry()

# Configure known providers with appropriate limits
# Gemini: 15 requests/minute for free tier, 60 for paid
_rate_limiters.configure("gemini", requests_per_minute=15, burst_size=5)
# LiteLLM (varies by backend, using conservative default)
_rate_limiters.configure("litellm", requests_per_minute=30, burst_size=10)


def get_rate_limiter(provider: str) -> RateLimiter:
    """Get the rate limiter for a provider."""
    return _rate_limiters.get(provider)


async def rate_limited_call(
    provider: str,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Execute a function with rate limiting.
    
    Args:
        provider: Provider name for rate limiting
        func: The async function to call
        *args: Positional arguments
        **kwargs: Keyword arguments
        
    Returns:
        The result of func
    """
    await _rate_limiters.acquire(provider)
    return await func(*args, **kwargs)


# Common retryable exceptions for API providers
API_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)

# Try to add common HTTP exceptions if available
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
    API_RETRYABLE_EXCEPTIONS = API_RETRYABLE_EXCEPTIONS + (
        HTTPStatusError,
        ConnectError,
        ReadTimeout,
    )
except ImportError:
    pass

try:
    from aiohttp import ClientError
    API_RETRYABLE_EXCEPTIONS = API_RETRYABLE_EXCEPTIONS + (ClientError,)
except ImportError:
    pass


# Pre-configured retry config for API calls
API_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    base_delay=2.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True,
    retryable_exceptions=API_RETRYABLE_EXCEPTIONS,
)
