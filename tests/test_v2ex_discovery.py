import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from regulated_workflow.errors import DiscoveryError, InputError
from regulated_workflow.leads import run_lead_assistant
from regulated_workflow.v2ex_discovery import (
    _fetch_official_topics,
    run_v2ex_discovery,
)


def _topic(topic_id, title, content, created=1787712000):
    return {
        "id": topic_id,
        "title": title,
        "content": content,
        "created": created,
        "node": {"name": "outsourcing"},
        "member": {"username": "must-not-be-saved"},
    }


class _FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, amount):
        return self.body[:amount]


class _FakeConnection:
    def __init__(self, host, timeout, response):
        self.host = host
        self.timeout = timeout
        self.response = response
        self.requests = []
        self.closed = False

    def request(self, method, path, headers):
        self.requests.append((method, path, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class V2EXDiscoveryTests(unittest.TestCase):
    def test_writes_minimized_contact_redacted_leads_csv(self):
        payload = [
            _topic(
                123,
                "有偿测试 RAG 文档工作流，长期有效",
                "需要 PDF 数据提取和 API 自动化。微信：secretwx，"
                "VX plainsecret，邮箱 buyer@example.com，电话 13800138000，TG: hidden_user，"
                "https://example.invalid/details，QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
            ),
            _topic(124, "平面设计", "只需要一张海报"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "v2ex.csv"

            with patch(
                "regulated_workflow.v2ex_discovery._fetch_official_topics",
                return_value=payload,
            ):
                run_v2ex_discovery(output)

            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(1, len(rows))
            row = rows[0]
            self.assertEqual("V2EX-123", row["lead_id"])
            self.assertEqual("v2ex", row["channel"])
            self.assertEqual("open", row["accepting_outreach"])
            self.assertEqual("https://www.v2ex.com/t/123", row["url"])
            self.assertEqual("", row["client_name"])
            serialized = " ".join(row.values())
            for secret in (
                "must-not-be-saved",
                "secretwx",
                "plainsecret",
                "buyer@example.com",
                "13800138000",
                "hidden_user",
                "example.invalid",
                "QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
            ):
                self.assertNotIn(secret, serialized)
            self.assertLessEqual(len(row["description"]), 280)

    def test_explicit_closed_status_is_compatible_with_lead_assistant(self):
        payload = [
            _topic(
                125,
                "外包需求：文档 API 工作流",
                "这是 RAG 数据提取需求，但已找到人。",
            ),
            _topic(
                126,
                "开发需求：PDF 表格处理",
                "需要 Python API 自动化，请提供可审阅结果。",
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_csv = root / "v2ex.csv"
            with patch(
                "regulated_workflow.v2ex_discovery._fetch_official_topics",
                return_value=payload,
            ):
                run_v2ex_discovery(input_csv)

            run_lead_assistant(
                input_csv,
                root / "ranked",
                as_of="2026-08-26T08:00:00Z",
            )

            with (root / "ranked" / "ranked_leads.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = {row["lead_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual("false", rows["V2EX-125"]["qualified"])
            self.assertEqual("false", rows["V2EX-125"]["accepting_outreach"])
            self.assertEqual("unknown", rows["V2EX-126"]["accepting_outreach"])

    def test_max_topics_bounds_items_examined(self):
        payload = [
            _topic(1, "不相关", "海报"),
            _topic(2, "开发预算：PDF API", "文档工作流"),
            _topic(3, "项目需求：RAG API", "知识库自动化"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "v2ex.csv"
            with patch(
                "regulated_workflow.v2ex_discovery._fetch_official_topics",
                return_value=payload,
            ):
                run_v2ex_discovery(output, max_topics=2)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(["V2EX-2"], [row["lead_id"] for row in rows])

    def test_filters_seller_and_high_risk_real_shapes_and_redacts_bracket_contact(self):
        payload = [
            _topic(
                1236194,
                "【接单】承接 AI、RAG、API 项目",
                "专业开发团队，提供开发服务。",
            ),
            _topic(
                1235642,
                "个人开发者可接外包",
                "可做 PDF 文档和 API 自动化。",
            ),
            _topic(
                1235316,
                "工作室对外承接开发",
                "提供 RAG 知识库和工作流服务。",
            ),
            _topic(
                1236030,
                "外包需求：AI 心理咨询 RAG",
                "有偿开发心理治疗建议工作流。",
            ),
            _topic(
                1236070,
                "有偿测试：RAG 文档工作流",
                "需要测试 PDF 数据提取和 API。vx[base64]：U2l0ZXJMb28=",
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "v2ex.csv"
            with patch(
                "regulated_workflow.v2ex_discovery._fetch_official_topics",
                return_value=payload,
            ):
                run_v2ex_discovery(output)

            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(["V2EX-1236070"], [row["lead_id"] for row in rows])
            row = rows[0]
            self.assertEqual(
                "discovery gates: buyer_intent=yes; seller_offer=no; "
                "high_risk=no; matched_themes=document,workflow,api,ai_retrieval",
                row["notes"],
            )
            serialized = " ".join(row.values())
            self.assertNotIn("vx[base64]", serialized.casefold())
            self.assertNotIn("U2l0ZXJMb28=", serialized)

    def test_transport_uses_one_fixed_https_host_without_credentials(self):
        body = json.dumps([]).encode("utf-8")
        connections = []

        def factory(host, timeout):
            connection = _FakeConnection(host, timeout, _FakeResponse(body))
            connections.append(connection)
            return connection

        self.assertEqual([], _fetch_official_topics(connection_factory=factory))
        self.assertEqual(1, len(connections))
        connection = connections[0]
        self.assertEqual("www.v2ex.com", connection.host)
        self.assertEqual(8, connection.timeout)
        self.assertEqual(1, len(connection.requests))
        method, path, headers = connection.requests[0]
        self.assertEqual("GET", method)
        self.assertEqual("/api/topics/show.json?node_name=outsourcing", path)
        self.assertIn("User-Agent", headers)
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)
        self.assertTrue(connection.closed)

    def test_transport_refuses_redirects_and_oversized_responses(self):
        def redirect_factory(host, timeout):
            return _FakeConnection(host, timeout, _FakeResponse(b"", status=302))

        with self.assertRaisesRegex(DiscoveryError, "refuses redirects"):
            _fetch_official_topics(connection_factory=redirect_factory)

        def oversized_factory(host, timeout):
            return _FakeConnection(
                host,
                timeout,
                _FakeResponse(b"[]", headers={"Content-Length": str(129 * 1024)}),
            )

        with self.assertRaisesRegex(DiscoveryError, "size limit"):
            _fetch_official_topics(connection_factory=oversized_factory)

        def undeclared_oversized_factory(host, timeout):
            return _FakeConnection(
                host,
                timeout,
                _FakeResponse(b"x" * (128 * 1024 + 1)),
            )

        with self.assertRaisesRegex(DiscoveryError, "size limit"):
            _fetch_official_topics(connection_factory=undeclared_oversized_factory)

    def test_transport_rejects_invalid_json(self):
        def factory(host, timeout):
            return _FakeConnection(host, timeout, _FakeResponse(b"not-json"))

        with self.assertRaisesRegex(DiscoveryError, "invalid UTF-8 JSON"):
            _fetch_official_topics(connection_factory=factory)

    def test_rejects_unbounded_cli_values_and_non_csv_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(InputError, "between 1 and 20"):
                run_v2ex_discovery(
                    Path(temp_dir) / "v2ex.csv",
                    max_topics=21,
                )
            with self.assertRaisesRegex(InputError, "must be a .csv"):
                run_v2ex_discovery(
                    Path(temp_dir) / "v2ex.json",
                )


if __name__ == "__main__":
    unittest.main()
