import unittest
from web.beta_ingress import BetaIngress


class IngressTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.calls = []
        def downstream(env, start):
            self.calls.append(env)
            start("401 Unauthorized", [])
            return [b"signature required"]
        self.app = BetaIngress(downstream, burst=2, per_second=1, clock=lambda: self.now)

    def request(self, path, method="GET"):
        result = []
        body = b"".join(self.app({"PATH_INFO": path, "REQUEST_METHOD": method},
                                lambda status, headers: result.append((status, headers))))
        return result[0][0], body

    def test_health_does_not_call_line(self):
        self.assertEqual(self.request("/healthz"), ("200 OK", b"ok"))
        self.assertEqual(self.calls, [])

    def test_unknown_and_wrong_method_denied(self):
        self.assertEqual(self.request("/admin")[0], "404 Not Found")
        self.assertEqual(self.request("/line-shared/webhook")[0], "405 Method Not Allowed")
        self.assertEqual(self.calls, [])

    def test_signature_handler_not_bypassed(self):
        self.assertEqual(self.request("/line-shared/webhook", "POST")[0], "401 Unauthorized")
        self.assertEqual(len(self.calls), 1)

    def test_rate_limit_and_refill(self):
        self.request("/healthz")
        self.request("/healthz")
        self.assertEqual(self.request("/healthz")[0], "429 Too Many Requests")
        self.now += 1
        self.assertEqual(self.request("/healthz")[0], "200 OK")

    def test_trailing_path_denied(self):
        self.assertEqual(self.request("/line-shared/webhook/", "POST")[0], "404 Not Found")
        self.assertEqual(self.calls, [])
