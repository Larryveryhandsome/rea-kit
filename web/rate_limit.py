"""簡單的每秒限流（token bucket），超過回 429。"""
import threading
import time


class RateLimited:
    """每秒 2 次、最多連 20 次（跟 webhook 入口同一種做法），超過回 429。"""
    def __init__(self, app, *, burst=20, per_second=2, clock=time.monotonic):
        self.app, self.burst, self.per_second, self.clock = app, burst, per_second, clock
        self.tokens, self.updated, self.lock = float(burst), clock(), threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + max(0, now - self.updated) * self.per_second)
            self.updated = now
            ok = self.tokens >= 1
            if ok:
                self.tokens -= 1
        if not ok:
            start_response("429 Too Many Requests", [("Content-Type", "text/plain"), ("Retry-After", "1")])
            return [b"rate limited"]
        return self.app(environ, start_response)
