import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from regulated_workflow.errors import LLMConfigurationError, LLMRequestError
from regulated_workflow.llm import OpenAICompatibleAdapter


class OpenAICompatibleAdapterTests(unittest.TestCase):
    def test_requires_all_configuration_from_environment_mapping(self):
        with self.assertRaisesRegex(LLMConfigurationError, "BASE_URL"):
            OpenAICompatibleAdapter.from_env({})

    def test_rejects_plain_http_for_remote_host(self):
        with self.assertRaisesRegex(LLMConfigurationError, "HTTPS"):
            OpenAICompatibleAdapter.from_env(
                {
                    "REGULATED_WORKFLOW_OPENAI_BASE_URL": "http://example.com/v1",
                    "REGULATED_WORKFLOW_OPENAI_API_KEY": "test-only",
                    "REGULATED_WORKFLOW_OPENAI_MODEL": "test-model",
                }
            )

    def test_allows_local_compatible_endpoint(self):
        adapter = OpenAICompatibleAdapter.from_env(
            {
                "REGULATED_WORKFLOW_OPENAI_BASE_URL": "http://127.0.0.1:8000/v1",
                "REGULATED_WORKFLOW_OPENAI_API_KEY": "test-only",
                "REGULATED_WORKFLOW_OPENAI_MODEL": "test-model",
            }
        )
        self.assertEqual("test-model", adapter.model)

    def test_redirect_is_rejected_without_forwarding_authorization(self):
        redirect_authorization = []
        target_authorization = []

        class TargetHandler(BaseHTTPRequestHandler):
            def _record_request(self):
                target_authorization.append(self.headers.get("Authorization"))
                payload = json.dumps(
                    {"choices": [{"message": {"content": "should not be reached"}}]}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _record_request
            do_POST = _record_request

            def log_message(self, format, *args):
                return

        target_server, target_thread = self._start_server(TargetHandler)
        target_url = "http://127.0.0.1:%d/redirect-target" % target_server.server_port

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                redirect_authorization.append(self.headers.get("Authorization"))
                self.send_response(302)
                self.send_header("Location", target_url)
                self.end_headers()

            def log_message(self, format, *args):
                return

        redirect_server, redirect_thread = self._start_server(RedirectHandler)
        adapter = OpenAICompatibleAdapter(
            base_url="http://127.0.0.1:%d/v1" % redirect_server.server_port,
            api_key="sentinel-secret",
            model="test-model",
        )

        try:
            with patch.dict(
                os.environ,
                {"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"},
                clear=False,
            ):
                with self.assertRaisesRegex(LLMRequestError, "302"):
                    adapter.draft_summary("Documents: 1")
        finally:
            for server in (redirect_server, target_server):
                server.shutdown()
                server.server_close()
            for thread in (redirect_thread, target_thread):
                thread.join(timeout=2)

        self.assertEqual(["Bearer sentinel-secret"], redirect_authorization)
        self.assertEqual([], target_authorization)

    @staticmethod
    def _start_server(handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        thread.start()
        return server, thread


if __name__ == "__main__":
    unittest.main()
