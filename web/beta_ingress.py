"""Bounded, single-process ingress guard for owner synthetic beta.

Origin rate limiting is defense in depth, not a replacement for edge rules.
No client identifiers, bodies or signatures are retained.
"""
import threading
import time


class BetaIngress:
    def __init__(self, downstream, *, burst=30, per_second=2, clock=time.monotonic):
        if burst <= 0 or per_second <= 0:
            raise ValueError("Positive limits required")
        self.downstream = downstream
        self.burst = burst
        self.per_second = per_second
        self.clock = clock
        self.tokens = float(burst)
        self.updated = clock()
        self.lock = threading.Lock()

    @staticmethod
    def respond(start_response, status, body, extra=()):
        start_response(status, [("Content-Type", "text/plain"),
                                ("Content-Length", str(len(body))), *extra])
        return [body]

    def __call__(self, environ, start_response):
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + max(0, now-self.updated)*self.per_second)
            self.updated = now
            allowed = self.tokens >= 1
            if allowed:
                self.tokens -= 1
        if not allowed:
            return self.respond(start_response, "429 Too Many Requests", b"rate limited",
                                [("Retry-After", "1")])
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "")
        if (path, method) == ("/healthz", "GET"):
            return self.respond(start_response, "200 OK", b"ok")
        if path != "/line-shared/webhook":
            return self.respond(start_response, "404 Not Found", b"not found")
        if method != "POST":
            return self.respond(start_response, "405 Method Not Allowed", b"method not allowed",
                                [("Allow", "POST")])
        return self.downstream(environ, start_response)
