from __future__ import annotations

import http.client
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Sequence

from .errors import DiscoveryError, InputError
from .output import write_csv


V2EX_LEAD_FIELDS = (
    "lead_id",
    "channel",
    "title",
    "description",
    "published_at",
    "age_hours",
    "proposals",
    "payment_verified",
    "accepting_outreach",
    "url",
    "client_name",
    "notes",
)

_HOST = "www.v2ex.com"
_TOPICS_PATH = "/api/topics/show.json?node_name=outsourcing"
_TIMEOUT_SECONDS = 8
_MAX_RESPONSE_BYTES = 128 * 1024
_MAX_OFFICIAL_TOPICS = 20
_MAX_SUMMARY_CHARS = 280
_USER_AGENT = "regulated-workflow-demo/0.1 (explicit read-only V2EX discovery)"

_MATCH_TERMS: Mapping[str, Sequence[str]] = {
    "document": ("document", "pdf", "excel", "csv", "spreadsheet", "文档", "表格", "数据提取"),
    "workflow": ("workflow", "automation", "pipeline", "工作流", "自动化", "数据管道"),
    "api": ("api", "integration", "接口", "集成"),
    "ai_retrieval": (
        "rag",
        "retrieval",
        "llm",
        "ai agent",
        "knowledge base",
        "大模型",
        "智能体",
        "知识库",
        "检索",
    ),
}

_CLOSED_TERMS = (
    "已找到人",
    "已找到合作",
    "已选定",
    "已招到",
    "已结束",
    "已关闭",
    "不再需要",
    "停止招聘",
    "暂停招聘",
    "需求关闭",
)
_OPEN_TERMS = (
    "长期有效",
    "持续招募",
    "继续招募",
    "仍在招",
    "还在招",
    "欢迎联系",
)

_BUYER_INTENT_TERMS = (
    "有偿测试",
    "付费测试",
    "招募测试",
    "外包需求",
    "项目需求",
    "开发需求",
    "需要开发",
    "寻找开发",
    "寻求开发",
    "找人开发",
    "找开发",
    "请人开发",
    "招募开发",
    "招聘开发",
    "开发预算",
    "项目预算",
    "预算",
    "请报价",
    "有偿",
    "付费",
    "悬赏",
    "hiring",
    "looking for a developer",
    "looking for developers",
    "paid test",
    "paid pilot",
)

_SELLER_OFFER_TERMS = (
    "接单",
    "承接",
    "可接项目",
    "可接外包",
    "提供开发服务",
    "提供技术服务",
    "寻项目",
    "求项目",
    "工作室对外",
    "开发团队对外",
    "远程接单",
    "专业开发团队",
    "available for work",
    "available for projects",
    "we offer",
    "our services",
)

_HIGH_RISK_TERMS = (
    "医疗",
    "医学",
    "医学诊断",
    "诊断",
    "治疗",
    "病历",
    "患者",
    "心理",
    "心理咨询",
    "心理治疗",
    "精神科",
    "处方",
    "法律意见",
    "法律咨询",
    "法律",
    "律师",
    "诉讼",
    "仲裁",
    "量化交易",
    "量化",
    "自动交易",
    "交易机器人",
    "投资建议",
    "股票交易",
    "股票",
    "证券交易",
    "证券",
    "期货交易",
    "期货",
    "外汇交易",
    "外汇",
    "加密货币交易",
    "加密货币",
    "币圈",
    "合约交易",
    "金融交易",
    "medical diagnosis",
    "mental health",
    "legal advice",
    "automated trading",
    "trading bot",
    "investment advice",
)

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_AT_HANDLE_RE = re.compile(r"(?<![\w@])@[A-Z0-9_][A-Z0-9_.-]{2,}", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d(?:[-\s]?\d){8}(?!\d)")
_LONG_NUMBER_RE = re.compile(r"(?<!\d)(?:\d[-\s]?){7,15}(?!\d)")
_CONTACT_LABEL_RE = re.compile(
    r"(?:联系方式|联系我|加我|加微信|微信号?|微信|wechat|telegram|tg|vx|wx|qq|邮箱|e-?mail|电话|手机)"
    r"\s*(?:号|账号)?\s*(?:\[[^\]\r\n]{1,24}\])?"
    r"\s*(?:(?:[:：]|是|为)\s*|\s+)[^\s,;，；]{2,}",
    re.IGNORECASE,
)
_OPAQUE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{8,}={1,2}|[A-Za-z0-9+/]{24,})(?![A-Za-z0-9+/])"
)


def run_v2ex_discovery(
    output_path: Path,
    max_topics: int = _MAX_OFFICIAL_TOPICS,
) -> Path:
    """Fetch one bounded public V2EX node page and write lead-assistant CSV."""
    output_path = output_path.expanduser()
    if output_path.suffix.casefold() != ".csv":
        raise InputError("V2EX discovery output must be a .csv file")
    if output_path.exists() and output_path.is_dir():
        raise InputError("V2EX discovery output is a directory: %s" % output_path)
    if not 1 <= max_topics <= _MAX_OFFICIAL_TOPICS:
        raise InputError("--max-topics must be between 1 and %d" % _MAX_OFFICIAL_TOPICS)

    payload = _fetch_official_topics()
    rows = _topic_rows(payload, max_topics=max_topics)
    write_csv(output_path, rows, fieldnames=V2EX_LEAD_FIELDS)
    return output_path


def _fetch_official_topics(
    connection_factory: Callable[..., Any] = http.client.HTTPSConnection,
) -> Any:
    """Perform exactly one HTTPS request to the fixed, no-auth official host."""
    connection = connection_factory(_HOST, timeout=_TIMEOUT_SECONDS)
    try:
        connection.request(
            "GET",
            _TOPICS_PATH,
            headers={
                "Accept": "application/json",
                "User-Agent": _USER_AGENT,
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise DiscoveryError("V2EX discovery refuses redirects")
        if response.status != 200:
            raise DiscoveryError("V2EX discovery returned HTTP %d" % response.status)
        raw_length = response.getheader("Content-Length")
        if raw_length:
            try:
                declared_length = int(raw_length)
            except ValueError as exc:
                raise DiscoveryError("V2EX returned an invalid Content-Length") from exc
            if declared_length > _MAX_RESPONSE_BYTES:
                raise DiscoveryError("V2EX response exceeds the size limit")
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise DiscoveryError("V2EX response exceeds the size limit")
    except DiscoveryError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise DiscoveryError("V2EX discovery request failed: %s" % exc) from exc
    finally:
        connection.close()

    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("V2EX returned invalid UTF-8 JSON") from exc


def _topic_rows(payload: Any, max_topics: int) -> List[Dict[str, Any]]:
    if not isinstance(payload, list):
        raise DiscoveryError("V2EX topic response must be a JSON array")

    rows: List[Dict[str, Any]] = []
    seen_ids = set()
    for topic in payload[:max_topics]:
        if not isinstance(topic, dict):
            continue
        topic_id = topic.get("id")
        title = topic.get("title")
        content = topic.get("content")
        created = topic.get("created")
        node = topic.get("node")
        if (
            isinstance(topic_id, bool)
            or not isinstance(topic_id, int)
            or topic_id <= 0
            or topic_id in seen_ids
            or not isinstance(title, str)
            or not isinstance(content, str)
            or isinstance(created, bool)
            or not isinstance(created, (int, float))
            or not isinstance(node, dict)
            or node.get("name") != "outsourcing"
        ):
            continue
        seen_ids.add(topic_id)
        haystack = "%s\n%s" % (title.casefold(), content.casefold())
        themes = _matched_themes(haystack)
        buyer_intent = _contains_any(haystack, _BUYER_INTENT_TERMS)
        seller_offer = _contains_any(haystack, _SELLER_OFFER_TERMS)
        high_risk = _contains_any(haystack, _HIGH_RISK_TERMS)
        if not themes or not buyer_intent or seller_offer or high_risk:
            continue
        clean_title = _sanitize_text(title, max_chars=240)
        clean_summary = _sanitize_text(content, max_chars=_MAX_SUMMARY_CHARS)
        if not clean_title or not clean_summary:
            continue
        try:
            published_at = datetime.fromtimestamp(float(created), timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
        status = _availability_status(haystack)
        rows.append(
            {
                "lead_id": "V2EX-%d" % topic_id,
                "channel": "v2ex",
                "title": clean_title,
                "description": clean_summary,
                "published_at": published_at.isoformat().replace("+00:00", "Z"),
                "age_hours": "",
                "proposals": "",
                "payment_verified": "",
                "accepting_outreach": status,
                "url": "https://www.v2ex.com/t/%d" % topic_id,
                "client_name": "",
                "notes": (
                    "discovery gates: buyer_intent=yes; seller_offer=no; "
                    "high_risk=no; matched_themes=%s" % ",".join(themes)
                ),
            }
        )
    return rows


def _matched_themes(haystack: str) -> List[str]:
    return [
        theme
        for theme, terms in _MATCH_TERMS.items()
        if any(_contains_term(haystack, term) for term in terms)
    ]


def _contains_term(haystack: str, term: str) -> bool:
    if term.isascii() and re.fullmatch(r"[a-z0-9]+", term):
        return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term), haystack) is not None
    return term in haystack


def _contains_any(haystack: str, terms: Sequence[str]) -> bool:
    return any(_contains_term(haystack, term) for term in terms)


def _availability_status(haystack: str) -> str:
    if any(term in haystack for term in _CLOSED_TERMS):
        return "closed"
    if any(term in haystack for term in _OPEN_TERMS):
        return "open"
    return "unknown"


def _sanitize_text(value: str, max_chars: int) -> str:
    """Remove contact channels and opaque payloads without trying to decode them."""
    text = _URL_RE.sub(" [link removed] ", value)
    text = _EMAIL_RE.sub(" [contact removed] ", text)
    text = _CONTACT_LABEL_RE.sub(" [contact removed] ", text)
    text = _PHONE_RE.sub(" [contact removed] ", text)
    text = _LONG_NUMBER_RE.sub(" [contact removed] ", text)
    text = _AT_HANDLE_RE.sub(" [contact removed] ", text)
    text = _OPAQUE_TOKEN_RE.sub(" [opaque token removed] ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
