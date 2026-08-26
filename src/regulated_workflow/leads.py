from __future__ import annotations

import csv
import hashlib
import html
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .errors import InputError
from .output import write_csv, write_jsonl, write_text


RANKED_LEAD_FIELDS = (
    "rank",
    "lead_id",
    "channel",
    "title",
    "client_name",
    "url",
    "published_at",
    "age_hours",
    "proposals",
    "payment_verified",
    "accepting_outreach",
    "match_themes",
    "recency_points",
    "proposal_points",
    "payment_points",
    "match_points",
    "channel_points",
    "applicable_points",
    "applicable_max",
    "score",
    "qualified",
    "draft_type",
    "qualification_notes",
    "notes",
)

_REQUIRED_COLUMNS = {"lead_id", "channel", "title", "description"}
_CHANNEL_ALIASES = {
    "upwork": "upwork",
    "v2ex": "v2ex",
    "proginn": "proginn",
    "programmer inn": "proginn",
    "程序员客栈": "proginn",
    "public": "public",
    "public post": "public",
    "公开需求": "public",
    "公开需求帖": "public",
}
_CHANNEL_POINTS = {"upwork": 5, "v2ex": 5, "proginn": 5, "public": 4}
_MATCH_TERMS: Mapping[str, Tuple[str, ...]] = {
    "document": (
        "document",
        "pdf",
        "spreadsheet",
        "excel",
        "csv",
        "data extraction",
        "document processing",
        "文档",
        "表格",
        "数据提取",
    ),
    "auditability": (
        "audit",
        "traceable",
        "evidence",
        "citation",
        "source reference",
        "human review",
        "quality",
        "compliance",
        "regulated",
        "validation",
        "审计",
        "证据",
        "引用",
        "来源",
        "人工复核",
        "质量",
        "合规",
        "校验",
    ),
    "automation": (
        "workflow",
        "automation",
        "python",
        "api integration",
        "api",
        "etl",
        "pipeline",
        "工作流",
        "自动化",
        "接口",
        "数据管道",
    ),
    "ai_retrieval": (
        "rag",
        "retrieval",
        "llm",
        "ai agent",
        "ai automation",
        "knowledge base",
        "vector search",
        "检索",
        "大模型",
        "知识库",
        "智能体",
    ),
}
_TRUE_VALUES = {"1", "true", "yes", "y", "verified", "payment verified", "是", "已验证"}
_FALSE_VALUES = {
    "0",
    "false",
    "no",
    "n",
    "unverified",
    "payment unverified",
    "否",
    "未验证",
}
_OUTREACH_TRUE_VALUES = {"1", "true", "yes", "y", "open", "accepting", "是", "开放", "可联系"}
_OUTREACH_FALSE_VALUES = {"0", "false", "no", "n", "closed", "not accepting", "否", "关闭", "已关闭", "不接单"}


@dataclass(frozen=True)
class Lead:
    lead_id: str
    channel: str
    title: str
    description: str
    client_name: str
    url: str
    published_at: str
    age_hours: float
    proposals: Optional[int]
    payment_verified: Optional[bool]
    accepting_outreach: Optional[bool]
    notes: str


@dataclass(frozen=True)
class ScoredLead:
    lead: Lead
    themes: Tuple[str, ...]
    recency_points: int
    proposal_points: int
    payment_points: int
    match_points: int
    channel_points: int
    applicable_points: int
    applicable_max: int
    score: int
    qualified: bool
    qualification_notes: str

    @property
    def draft_type(self) -> str:
        if not self.qualified:
            return "none"
        return "upwork_english" if self.lead.channel == "upwork" else "domestic_chinese"


def run_lead_assistant(
    input_path: Path,
    output_dir: Path,
    as_of: Optional[str] = None,
) -> Sequence[Path]:
    """Rank a manually supplied CSV and create drafts without any network action."""
    input_path = input_path.expanduser()
    output_dir = output_dir.expanduser()
    if not input_path.is_file():
        raise InputError("lead input is not a readable CSV file: %s" % input_path)
    if input_path.suffix.casefold() != ".csv":
        raise InputError("lead input must be a .csv file")

    output_names = {
        "ranked_leads.csv",
        "upwork_proposals.md",
        "domestic_messages.md",
        "summary.md",
        "audit.jsonl",
    }
    resolved_input = input_path.resolve()
    if any(
        resolved_input == (output_dir / output_name).resolve()
        for output_name in output_names
    ):
        raise InputError("output would overwrite the lead input file: %s" % input_path)

    parsed_as_of = _parse_datetime(as_of, "--as-of") if as_of else datetime.now(timezone.utc)
    leads = _read_leads(input_path, parsed_as_of)
    scored = [_score_lead(lead) for lead in leads]
    ranked = sorted(
        scored,
        key=lambda item: (
            not item.qualified,
            -item.score,
            item.lead.age_hours,
            item.lead.lead_id.casefold(),
        ),
    )

    ranked_path = output_dir / "ranked_leads.csv"
    upwork_path = output_dir / "upwork_proposals.md"
    domestic_path = output_dir / "domestic_messages.md"
    summary_path = output_dir / "summary.md"
    audit_path = output_dir / "audit.jsonl"
    write_csv(
        ranked_path,
        [_ranked_row(index, item) for index, item in enumerate(ranked, start=1)],
        fieldnames=RANKED_LEAD_FIELDS,
    )
    write_text(upwork_path, _upwork_drafts(ranked))
    write_text(domestic_path, _domestic_drafts(ranked))
    write_text(summary_path, _summary(ranked))
    input_bytes = input_path.read_bytes()
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    write_jsonl(
        audit_path,
        (
            {
                "event": "lead_ranking_started",
                "timestamp": timestamp,
                "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
                "lead_count": len(ranked),
                "as_of": parsed_as_of.isoformat().replace("+00:00", "Z"),
                "scoring_version": 1,
                "network_mode": "offline",
            },
            {
                "event": "lead_ranking_completed",
                "timestamp": timestamp,
                "qualified_count": sum(item.qualified for item in ranked),
                "upwork_draft_count": sum(
                    item.draft_type == "upwork_english" for item in ranked
                ),
                "domestic_draft_count": sum(
                    item.draft_type == "domestic_chinese" for item in ranked
                ),
                "external_action_performed": False,
                "human_review_required": True,
            },
        ),
    )
    return (ranked_path, upwork_path, domestic_path, summary_path, audit_path)


def count_english_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text))


def _read_leads(input_path: Path, as_of: datetime) -> List[Lead]:
    try:
        handle = input_path.open(encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise InputError("cannot read lead CSV: %s" % exc) from exc

    try:
        with handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise InputError("lead CSV must contain a header row")
            headers = [header.strip() if header else "" for header in reader.fieldnames]
            if len(set(headers)) != len(headers):
                raise InputError("lead CSV contains duplicate column names")
            missing = sorted(_REQUIRED_COLUMNS - set(headers))
            if missing:
                raise InputError(
                    "lead CSV is missing required columns: %s" % ", ".join(missing)
                )
            reader.fieldnames = headers
            leads: List[Lead] = []
            seen_ids = set()
            for row_number, raw_row in enumerate(reader, start=2):
                row = {
                    key: (value or "").strip()
                    for key, value in raw_row.items()
                    if key
                }
                if not any(row.values()):
                    continue
                lead = _parse_lead(row, row_number, as_of)
                folded_id = lead.lead_id.casefold()
                if folded_id in seen_ids:
                    raise InputError(
                        "lead CSV row %d duplicates lead_id %r"
                        % (row_number, lead.lead_id)
                    )
                seen_ids.add(folded_id)
                leads.append(lead)
    except (UnicodeError, csv.Error) as exc:
        raise InputError("cannot parse lead CSV: %s" % exc) from exc
    if not leads:
        raise InputError("lead CSV contains no lead rows")
    return leads


def _parse_lead(row: Mapping[str, str], row_number: int, as_of: datetime) -> Lead:
    lead_id = row.get("lead_id", "")
    title = row.get("title", "")
    description = row.get("description", "")
    if not lead_id:
        raise InputError("lead CSV row %d has an empty lead_id" % row_number)
    if not title:
        raise InputError("lead CSV row %d has an empty title" % row_number)
    if not description:
        raise InputError("lead CSV row %d has an empty description" % row_number)

    raw_channel = row.get("channel", "").casefold()
    channel = _CHANNEL_ALIASES.get(raw_channel)
    if channel is None:
        raise InputError(
            "lead CSV row %d has unsupported channel %r" % (row_number, row.get("channel", ""))
        )

    published_at = row.get("published_at", "")
    raw_age = row.get("age_hours", "")
    if raw_age:
        try:
            age_hours = float(raw_age)
        except ValueError as exc:
            raise InputError("lead CSV row %d has invalid age_hours" % row_number) from exc
    elif published_at:
        published = _parse_datetime(published_at, "published_at at row %d" % row_number)
        age_hours = (as_of - published).total_seconds() / 3600
    else:
        raise InputError(
            "lead CSV row %d needs age_hours or published_at" % row_number
        )
    if not math.isfinite(age_hours):
        raise InputError("lead CSV row %d needs a finite age_hours" % row_number)
    if age_hours < 0:
        raise InputError("lead CSV row %d has a future publication time" % row_number)

    proposals = _parse_proposals(row.get("proposals", ""), row_number)
    payment_verified = _parse_optional_bool(
        row.get("payment_verified", ""), row_number
    )
    accepting_outreach = _parse_accepting_outreach(
        row.get("accepting_outreach", ""), row_number
    )
    if channel == "upwork" and proposals is None:
        raise InputError("Upwork row %d needs proposals" % row_number)
    if channel == "upwork" and payment_verified is None:
        raise InputError("Upwork row %d needs payment_verified" % row_number)

    url = row.get("url", "")
    if url:
        parsed_url = urlsplit(url)
        if (
            any(character.isspace() for character in url)
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
        ):
            raise InputError("lead CSV row %d has an invalid public URL" % row_number)
        if parsed_url.username or parsed_url.password:
            raise InputError("lead CSV row %d URL must not contain credentials" % row_number)

    return Lead(
        lead_id=lead_id,
        channel=channel,
        title=title,
        description=description,
        client_name=row.get("client_name", ""),
        url=url,
        published_at=published_at,
        age_hours=age_hours,
        proposals=proposals,
        payment_verified=payment_verified,
        accepting_outreach=accepting_outreach,
        notes=row.get("notes", ""),
    )


def _parse_datetime(value: str, label: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InputError("%s must be a valid ISO-8601 timestamp" % label) from exc
    if parsed.tzinfo is None:
        raise InputError("%s must include a timezone" % label)
    return parsed.astimezone(timezone.utc)


def _parse_proposals(value: str, row_number: int) -> Optional[int]:
    normalized = value.strip().casefold()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)
    numbers = [int(number) for number in re.findall(r"\d+", normalized)]
    if ("less than" in normalized or normalized.startswith("<")) and len(numbers) == 1:
        return max(0, numbers[0] - 1)
    if len(numbers) == 2 and (" to " in normalized or "-" in normalized or "–" in normalized):
        return max(numbers)
    if len(numbers) == 1 and normalized.endswith("+"):
        return numbers[0]
    raise InputError("lead CSV row %d has invalid proposals" % row_number)


def _parse_optional_bool(value: str, row_number: int) -> Optional[bool]:
    normalized = value.strip().casefold()
    if not normalized:
        return None
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise InputError("lead CSV row %d has invalid payment_verified" % row_number)


def _parse_accepting_outreach(value: str, row_number: int) -> Optional[bool]:
    """Return availability only when the manually collected post states it clearly."""
    normalized = value.strip().casefold()
    if not normalized:
        return None
    if normalized in _OUTREACH_TRUE_VALUES:
        return True
    if normalized in _OUTREACH_FALSE_VALUES:
        return False
    raise InputError("lead CSV row %d has invalid accepting_outreach" % row_number)


def _score_lead(lead: Lead) -> ScoredLead:
    haystack = "%s\n%s" % (lead.title.casefold(), lead.description.casefold())
    themes = tuple(
        theme
        for theme, terms in _MATCH_TERMS.items()
        if any(_contains_term(haystack, term) for term in terms)
    )
    recency_points = 20 if lead.age_hours <= 2 else 0
    proposal_points = 15 if lead.proposals is not None and lead.proposals < 20 else 0
    payment_points = 20 if lead.payment_verified is True else 0
    match_points = min(40, len(themes) * 10)
    channel_points = _CHANNEL_POINTS[lead.channel]
    applicable_points = (
        recency_points
        + proposal_points
        + payment_points
        + match_points
        + channel_points
    )
    applicable_max = 100 if lead.channel == "upwork" else 65
    score = round(applicable_points * 100 / applicable_max)
    high_match = match_points >= 20
    outreach_gate = (
        lead.accepting_outreach is not False,
        "outreach is not explicitly closed",
    )
    if lead.channel == "upwork":
        gates = (
            (lead.age_hours <= 2, "posted within 2 hours"),
            (lead.proposals is not None and lead.proposals < 20, "fewer than 20 proposals"),
            (lead.payment_verified is True, "payment verified"),
            (high_match, "matches at least two demo themes"),
            outreach_gate,
        )
    else:
        gates = (
            (high_match, "matches at least two demo themes"),
            outreach_gate,
        )
    qualified = all(passed for passed, _ in gates)
    passed_labels = [label for passed, label in gates if passed]
    failed_labels = [label for passed, label in gates if not passed]
    note_parts = []
    if passed_labels:
        note_parts.append("passed: %s" % "; ".join(passed_labels))
    if failed_labels:
        note_parts.append("failed: %s" % "; ".join(failed_labels))
    if lead.accepting_outreach is None:
        note_parts.append("outreach availability: unknown")
    notes = " | ".join(note_parts)
    return ScoredLead(
        lead=lead,
        themes=themes,
        recency_points=recency_points,
        proposal_points=proposal_points,
        payment_points=payment_points,
        match_points=match_points,
        channel_points=channel_points,
        applicable_points=applicable_points,
        applicable_max=applicable_max,
        score=score,
        qualified=qualified,
        qualification_notes=notes,
    )


def _contains_term(haystack: str, term: str) -> bool:
    if term.isascii() and re.fullmatch(r"[a-z0-9]+", term):
        return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term), haystack) is not None
    return term in haystack


def _ranked_row(rank: int, item: ScoredLead) -> Dict[str, Any]:
    lead = item.lead
    return {
        "rank": rank,
        "lead_id": lead.lead_id,
        "channel": lead.channel,
        "title": lead.title,
        "client_name": lead.client_name,
        "url": lead.url,
        "published_at": lead.published_at,
        "age_hours": "%.2f" % lead.age_hours,
        "proposals": "" if lead.proposals is None else lead.proposals,
        "payment_verified": (
            "" if lead.payment_verified is None else str(lead.payment_verified).lower()
        ),
        "accepting_outreach": (
            "unknown"
            if lead.accepting_outreach is None
            else str(lead.accepting_outreach).lower()
        ),
        "match_themes": ";".join(item.themes),
        "recency_points": item.recency_points,
        "proposal_points": item.proposal_points,
        "payment_points": item.payment_points,
        "match_points": item.match_points,
        "channel_points": item.channel_points,
        "applicable_points": item.applicable_points,
        "applicable_max": item.applicable_max,
        "score": item.score,
        "qualified": str(item.qualified).lower(),
        "draft_type": item.draft_type,
        "qualification_notes": item.qualification_notes,
        "notes": lead.notes,
    }


def _upwork_drafts(ranked: Sequence[ScoredLead]) -> str:
    lines = [
        "# Upwork Proposal Drafts",
        "",
        "Drafts only. Review the original post and edit any assumption before manually submitting.",
    ]
    matching = [item for item in ranked if item.draft_type == "upwork_english"]
    if not matching:
        lines.extend(["", "No Upwork lead passed every gate."])
        return "\n".join(lines)
    for item in matching:
        proposal = _upwork_proposal(item)
        word_count = count_english_words(proposal)
        if not 120 <= word_count <= 160:
            raise RuntimeError("generated Upwork proposal is outside the 120-160 word limit")
        lines.extend(
            [
                "",
                "## %s — %s" % (_markdown_text(item.lead.lead_id), _markdown_text(item.lead.title)),
                "",
                "- Source: `%s`" % _code_text(item.lead.url or "not supplied"),
                "- Score: %d/100" % item.score,
                "- Proposal word count: %d" % word_count,
                "- Status: unsubmitted draft; human review required",
                "",
                proposal,
            ]
        )
    return "\n".join(lines)


def _upwork_proposal(item: ScoredLead) -> str:
    input_phrase = _english_input_phrase(item.themes)
    return "\n".join(
        [
            "Hi,",
            "",
            (
                "Your project appears to need a reliable way to turn %s into review-ready "
                "results without losing source traceability. I built a local-first demo that "
                "extracts structured evidence, records page or row references, assigns "
                "confidence, and sends uncertain items to a human review queue."
            )
            % input_phrase,
            "",
            "For a fixed first stage, I would:",
            "1. confirm the target fields and acceptance examples;",
            "2. build one extraction or validation workflow for up to 20 documents or 500 rows;",
            "3. deliver the output, audit trail, deployment notes, and one approval checkpoint.",
            "",
            (
                "I can complete this bounded pilot in 7 days for $149, including one revision "
                "and 7 days of defect support. It will run in your environment and will not "
                "send messages or change business data automatically. A matching synthetic "
                "demo is ready to share."
            ),
            "",
            (
                "What sample size are you working with, and how do you currently decide "
                "whether an extracted result is acceptable?"
            ),
            "",
            "Best,",
        ]
    )


def _english_input_phrase(themes: Sequence[str]) -> str:
    if "document" in themes:
        return "documents or spreadsheets"
    if "ai_retrieval" in themes:
        return "AI-assisted research inputs"
    if "auditability" in themes:
        return "review-sensitive records"
    return "repetitive workflow inputs"


def _domestic_drafts(ranked: Sequence[ScoredLead]) -> str:
    lines = [
        "# 国内渠道私信草稿",
        "",
        "仅作草稿。手工发送前必须回看原需求，不得群发、刷屏或先做免费客户专属成品。",
    ]
    matching = [item for item in ranked if item.draft_type == "domestic_chinese"]
    if not matching:
        lines.extend(["", "暂无国内渠道线索通过演示匹配门槛。"])
        return "\n".join(lines)
    for item in matching:
        bottleneck = _chinese_bottleneck(item.themes)
        lines.extend(
            [
                "",
                "## %s — %s" % (_markdown_text(item.lead.lead_id), _markdown_text(item.lead.title)),
                "",
                "- 渠道：`%s`" % _code_text(item.lead.channel),
                "- 来源：`%s`" % _code_text(item.lead.url or "未填写"),
                "- 得分：%d/100" % item.score,
                "- 状态：未发送草稿，必须人工复核",
                "",
                "你好，",
                "",
                "%s。" % bottleneck,
                "",
                (
                    "我有一个完全使用合成数据的可审计工作流演示，可以把文档或表格整理为"
                    "结构化结果、来源定位和人工复核队列。建议先做 7 日固定范围试点：一个数据源，"
                    "最多 20 份文档或 500 行，一条提取/校验流程，一个输出和一个人工审批点。首两单价格为 "
                    "¥999，包含部署说明、一次修改和 7 天缺陷支持。"
                ),
                "",
                (
                    "为判断是否匹配，只需确认两个问题：样本大约有多少份/多少行？"
                    "你们现在用什么标准验收提取结果？"
                ),
                "",
                "我不会先免费制作客户专属成品；确认范围后再开始。",
            ]
        )
    return "\n".join(lines)


def _chinese_bottleneck(themes: Sequence[str]) -> str:
    if "document" in themes and "auditability" in themes:
        return "这类需求的具体瓶颈通常是：人工复制文档或表格字段后，来源定位、漏项和复核状态很难一起维护"
    if "ai_retrieval" in themes:
        return "这类需求的具体瓶颈通常是：AI 结果与原始来源脱节，后续验收和人工复核成本较高"
    if "automation" in themes:
        return "这类需求的具体瓶颈通常是：重复流程已经耗时，但又缺少可检查的输出和人工审批边界"
    return "这类需求的具体瓶颈通常是：手工整理结果与验收依据分散，容易返工"


def _summary(ranked: Sequence[ScoredLead]) -> str:
    qualified = [item for item in ranked if item.qualified]
    return "\n".join(
        [
            "# Lead Review Summary",
            "",
            "- Leads scored: %d" % len(ranked),
            "- Qualified for a draft: %d" % len(qualified),
            "- Upwork English drafts: %d"
            % sum(item.draft_type == "upwork_english" for item in ranked),
            "- Domestic Chinese drafts: %d"
            % sum(item.draft_type == "domestic_chinese" for item in ranked),
            "- External actions performed: none",
            "",
            "## Rules",
            "",
            "- Upwork requires age <= 2 hours, proposals < 20, verified payment, and at least two demo-match themes.",
            "- Domestic channels require at least two demo-match themes; recency still increases rank, while proposals and payment are treated as not applicable when blank.",
            "- Ranking places qualified leads first, then sorts by score, recency, and stable lead ID.",
            "- Match themes are deterministic keyword groups: document, auditability, automation, and AI/retrieval.",
            "",
            "## Human Boundary",
            "",
            "Every message is an unsubmitted draft. Review the original post, edit assumptions, check platform rules, and send manually. Do not bulk-send, auto-refresh, scrape authenticated pages, or promise an outcome that was not demonstrated.",
        ]
    )


def _markdown_text(value: str) -> str:
    collapsed = " ".join(value.split())[:160]
    escaped = html.escape(collapsed, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", escaped)


def _code_text(value: str) -> str:
    return " ".join(value.split()).replace("`", "'")[:500]
