"""Telegram flood control and rate limit handling.

Wraps Telegram Bot API calls to handle:
- RetryAfter (flood control) with automatic waiting
- Adaptive backoff for repeated violations
- Message throttling to prevent rate limits
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Optional, TypeVar

try:
    from telegram.error import RetryAfter
except ImportError:
    # Mock RetryAfter for testing without telegram installed
    class RetryAfter(Exception):
        def __init__(self, retry_after: float):
            self.retry_after = retry_after
            super().__init__(f"RetryAfter: {retry_after}s")

logger = logging.getLogger(__name__)

T = TypeVar("T")


class FloodControlState:
    """Track flood control state for adaptive backoff."""

    def __init__(self, max_strikes: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
        self.max_strikes = max_strikes
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.consecutive_strikes: int = 0
        self.blocked_until: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        """Check if currently under flood control."""
        return time.time() < self.blocked_until

    @property
    def wait_time(self) -> float:
        """Calculate current wait time with exponential backoff."""
        if not self.active:
            return 0.0
        return max(0.0, self.blocked_until - time.time())

    async def record_strike(self, retry_after: float) -> None:
        """Record a flood control strike and update backoff."""
        async with self._lock:
            self.consecutive_strikes += 1
            self.blocked_until = time.time() + retry_after
            backoff = min(
                self.base_delay * (2 ** (self.consecutive_strikes - 1)),
                self.max_delay,
            )
            logger.warning(
                "[FloodControl] Strike %d/%d: RetryAfter %.1fs, backoff %.1fs",
                self.consecutive_strikes, self.max_strikes, retry_after, backoff,
            )
            if self.consecutive_strikes >= self.max_strikes:
                logger.warning(
                    "[FloodControl] Max strikes reached. Entering cooldown mode."
                )

    async def record_success(self) -> None:
        """Reset strike counter on successful request."""
        async with self._lock:
            if self.consecutive_strikes > 0:
                logger.info(
                    "[FloodControl] Resetting %d strikes after successful request",
                    self.consecutive_strikes,
                )
            self.consecutive_strikes = 0

    def should_throttle(self, min_interval: float = 1.0) -> bool:
        """Check if we should throttle requests to avoid rate limits."""
        if self.active:
            return True
        if self.consecutive_strikes > 0:
            return True
        return False


# Global flood control state
_flood_state: Optional[FloodControlState] = None


def get_flood_control() -> FloodControlState:
    """Get or create the global flood control state."""
    global _flood_state
    if _flood_state is None:
        _flood_state = FloodControlState()
    return _flood_state


async def safe_send(
    coro: Coroutine[Any, Any, T],
    *,
    flood_state: Optional[FloodControlState] = None,
) -> T:
    """Execute a Telegram API call with flood control handling.

    Args:
        coro: The coroutine to execute (e.g., bot.send_message(...))
        flood_state: Optional flood control state (uses global if not provided)

    Returns:
        The result of the coroutine

    Raises:
        Exception: If the coroutine fails after flood control handling
    """
    if flood_state is None:
        flood_state = get_flood_control()

    # Wait if currently under flood control
    wait = flood_state.wait_time
    if wait > 0:
        logger.info("[FloodControl] Waiting %.1fs before request", wait)
        await asyncio.sleep(wait)

    # Additional throttle delay if we've had recent strikes
    if flood_state.should_throttle():
        throttle_delay = min(
            flood_state.base_delay * (2 ** (self.consecutive_strikes - 1)),
            flood_state.max_delay / 2,
        )
        logger.debug("[FloodControl] Throttle delay: %.1fs", throttle_delay)
        await asyncio.sleep(throttle_delay)

    try:
        result = await coro
        await flood_state.record_success()
        return result
    except RetryAfter as e:
        await flood_state.record_strike(e.retry_after)
        logger.warning("[FloodControl] RetryAfter: %.1fs", e.retry_after)
        await asyncio.sleep(e.retry_after)
        # Retry once after waiting
        return await coro
    except Exception:
        # Don't reset strikes on non-flood errors
        raise


def split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split text into chunks respecting Telegram's UTF-16 character limit.

    Telegram uses UTF-16 code units, not bytes. This function ensures
    each chunk stays within the limit.

    Args:
        text: The text to split
        max_len: Maximum UTF-16 characters per chunk (default 4000, leaves room for formatting)

    Returns:
        List of text chunks, each within the limit
    """
    if len(text.encode("utf-16-le")) // 2 <= max_len:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        # Find last newline within limit for clean breaks
        cut = remaining.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            cut = max_len
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()

    return chunks


async def throttled_notify(
    send_func: Callable[..., Coroutine[Any, Any, Any]],
    event_type: str,
    cooldown: float = 5.0,
    **kwargs,
) -> Optional[Any]:
    """Send a notification with throttling to prevent rate limits.

    Args:
        send_func: The send function to call (e.g., bot.send_message)
        event_type: Unique identifier for this type of notification
        cooldown: Minimum seconds between notifications of this type
        **kwargs: Arguments to pass to send_func

    Returns:
        Result of send_func, or None if throttled
    """
    # Simple global throttle state
    if not hasattr(throttled_notify, "_last_sent"):
        throttled_notify._last_sent: dict[str, float] = {}

    now = time.time()
    last = throttled_notify._last_sent.get(event_type, 0)

    if now - last < cooldown:
        logger.debug("[FloodControl] Throttling notification '%s' (cooldown %.1fs)", event_type, cooldown)
        return None

    throttled_notify._last_sent[event_type] = now
    return await send_func(**kwargs)
