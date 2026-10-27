"""Loopback HTTP test of the deployment's WSGI app using installed Waitress."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from waitress import create_server
from adapters.storage import TenantStore
from adapters.line.shared import SharedChannelConfig
from adapters.line.signature import sign
from web.line_app import create_app


class WsgiSmokeTests(unittest.TestCase):
    def test_empty_signed_webhook_over_real_local_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(store=TenantStore(tmp), channel=SharedChannelConfig("test-secret", "test-token"))
            # Empty verification body does not instantiate a LINE client.
            server = create_server(app.wsgi, host="127.0.0.1", port=0, threads=1)
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.effective_port}/line-shared/webhook"
                body = json.dumps({"events": []}).encode()
                request = urllib.request.Request(url, data=body, headers={"X-Line-Signature": sign("test-secret", body)})
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                self.assertIsNone(app._client)
                with self.assertRaises(urllib.error.HTTPError) as err:
                    urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=5)
                self.assertEqual(err.exception.code, 403)
                err.exception.close()
            finally:
                # Drain request workers before closing their wake-up socket.
                server.task_dispatcher.shutdown()
                server.close()
                thread.join(timeout=2)
