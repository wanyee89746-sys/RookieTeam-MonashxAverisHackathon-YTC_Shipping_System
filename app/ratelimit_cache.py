"""Shared rate limiter + disk cache for Gemini calls.

Features:
- Conservative RPM limiter
- Automatic retry for temporary API errors
- Immediate stop for daily/project quota exhaustion
- Disk-backed LLM cache
- Thread-safe cache writes
"""

import hashlib
import json
import os
import threading
import time


CACHE_PATH = os.path.join(
    os.path.dirname(__file__),
    ".llm_cache.json",
)

_lock = threading.Lock()


class RateLimiter:
    """Simple rate limiter.

    Keeps Gemini calls separated to avoid hitting RPM limits.

    Default:
        12 calls/minute
        = approximately 1 call every 5 seconds

    This is intentionally conservative.
    """

    def __init__(self, calls_per_minute: int = 12):

        if calls_per_minute <= 0:
            raise ValueError(
                "calls_per_minute must be greater than 0"
            )

        self.min_interval = 60.0 / calls_per_minute

        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self):

        with self._lock:

            now = time.monotonic()

            elapsed = now - self._last_call

            if elapsed < self.min_interval:

                wait_time = self.min_interval - elapsed

                print(
                    f"[RATE LIMIT] waiting "
                    f"{wait_time:.1f}s"
                )

                time.sleep(wait_time)

            self._last_call = time.monotonic()


def _is_daily_quota_error(message: str) -> bool:
    """Detect errors caused by a daily/project quota.

    These errors should NOT be retried because waiting a few seconds
    will not restore the quota.
    """

    daily_quota_markers = (
        "PerDay",
        "per_day",
        "PER_DAY",
        "GenerateRequestsPerDayPerProjectPerModel",
        "generate_content_free_tier_requests",
        "daily quota",
        "daily limit",
        "quota exceeded",
        "You exceeded your current quota",
    )

    return any(
        marker in message
        for marker in daily_quota_markers
    )


def _is_transient_error(message: str) -> bool:
    """Detect errors that may recover after a short wait."""

    transient_markers = (
        "429",
        "RESOURCE_EXHAUSTED",
        "503",
        "UNAVAILABLE",
        "DEADLINE",
        "DEADLINE_EXCEEDED",
        "getaddrinfo",
        "temporarily unavailable",
    )

    return any(
        marker in message
        for marker in transient_markers
    )


def _extract_retry_delay(message: str):
    """Try to extract Google's suggested retry delay.

    Example:
        'Please retry in 42.590716545s.'
    """

    import re

    match = re.search(
        r"retry in ([0-9.]+)s",
        message,
        re.IGNORECASE,
    )

    if match:

        try:
            return float(match.group(1))
        except ValueError:
            pass

    return None


def call_with_backoff(
    fn,
    *args,
    max_retries=5,
    **kwargs,
):
    """Call a Gemini function with safe retry handling.

    Retry:
        Temporary 429 / 503 / network errors

    Do NOT retry:
        Daily/project quota exhaustion

    This prevents wasting time doing:
        retry → wait → retry → wait
    when the daily quota is already exhausted.
    """

    for attempt in range(max_retries):

        try:

            return fn(*args, **kwargs)

        except Exception as e:

            msg = str(e)

            # -----------------------------------------------------
            # DAILY QUOTA
            # -----------------------------------------------------
            if _is_daily_quota_error(msg):

                print()
                print("=" * 70)
                print("[QUOTA] Daily/project Gemini quota exhausted.")
                print("[QUOTA] No retry will be attempted.")
                print("[QUOTA] Save progress and resume later.")
                print("=" * 70)
                print()

                raise

            # -----------------------------------------------------
            # NON-TRANSIENT ERROR
            # -----------------------------------------------------
            if not _is_transient_error(msg):

                raise

            # -----------------------------------------------------
            # MAX RETRIES REACHED
            # -----------------------------------------------------
            if attempt == max_retries - 1:

                print(
                    f"[BACKOFF] maximum retries "
                    f"({max_retries}) reached"
                )

                raise

            # -----------------------------------------------------
            # RETRY DELAY
            # -----------------------------------------------------

            # If Google gives us a specific retry delay,
            # respect it.
            suggested_delay = _extract_retry_delay(msg)

            if suggested_delay is not None:

                wait_s = min(
                    120,
                    max(1, suggested_delay),
                )

            else:

                # Exponential backoff:
                #
                # retry 1 -> 5s
                # retry 2 -> 10s
                # retry 3 -> 20s
                # retry 4 -> 40s
                #
                wait_s = min(
                    60,
                    5 * (2 ** attempt),
                )

            print(
                f"[BACKOFF] retry "
                f"{attempt + 1}/{max_retries} "
                f"after {wait_s:.1f}s: "
                f"{msg[:200]}"
            )

            time.sleep(wait_s)


def _content_hash(*parts) -> str:
    """Create a stable SHA-256 hash from call inputs."""

    h = hashlib.sha256()

    for part in parts:

        h.update(
            str(part).encode(
                "utf-8",
                errors="replace",
            )
        )

        h.update(b"\x00")

    return h.hexdigest()


class LLMCache:
    """Disk-backed cache for Gemini calls.

    The cache survives:
        - program crashes
        - pipeline restarts
        - computer restarts
        - API quota exhaustion

    This prevents the same Gemini request from being made again
    unnecessarily.
    """

    def __init__(self, path=CACHE_PATH):

        self.path = path
        self._data = {}

        self._load()

    def _load(self):

        if not os.path.exists(self.path):

            print(
                f"[CACHE] no cache found: {self.path}"
            )

            return

        try:

            with open(
                self.path,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

            if isinstance(data, dict):

                self._data = data

                print(
                    f"[CACHE] loaded "
                    f"{len(self._data)} entries"
                )

            else:

                print(
                    "[CACHE] invalid cache format, "
                    "starting empty"
                )

        except Exception as e:

            print(
                f"[CACHE] failed to load cache: {e}"
            )

            self._data = {}

    def key(self, *parts) -> str:

        return _content_hash(*parts)

    def get(self, key):

        return self._data.get(key)

    def set(self, key, value):

        self._data[key] = value

        # ---------------------------------------------------------
        # Write the cache immediately.
        #
        # If the program crashes later, previous successful calls
        # are still saved.
        # ---------------------------------------------------------
        with _lock:

            temp_path = self.path + ".tmp"

            try:

                with open(
                    temp_path,
                    "w",
                    encoding="utf-8",
                ) as file:

                    json.dump(
                        self._data,
                        file,
                        ensure_ascii=False,
                        indent=2,
                    )

                # Atomic replacement:
                #
                # .tmp → actual cache
                #
                # This reduces the chance of corrupting the cache
                # if the program is interrupted during writing.
                os.replace(
                    temp_path,
                    self.path,
                )

            except Exception as e:

                print(
                    f"[CACHE] failed to save: {e}"
                )

                # Clean up temporary file if necessary
                try:

                    if os.path.exists(temp_path):
                        os.remove(temp_path)

                except Exception:
                    pass

    def clear(self):

        """Clear the entire cache."""

        with _lock:

            self._data = {}

            if os.path.exists(self.path):

                os.remove(self.path)

        print("[CACHE] cleared")

    def size(self) -> int:

        """Return number of cached entries."""

        return len(self._data)