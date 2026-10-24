"""Fail-closed news and macro data primitives for Smart Money Hub.

This module is intentionally not wired into the running publisher yet. Its
outputs are persisted as research/preview material; channel publication and
automatic Telegram alerts require a separately tested activation step.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import socket
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .gemini_coach import GEMINI_MODEL

logger = logging.getLogger(__name__)

FED_PRESS_RELEASES_RSS = "https://www.federalreserve.gov/feeds/press_all.xml"
TREASURY_DAILY_YIELDS_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
BLS_API_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BEA_API_DATA = "https://apps.bea.gov/api/data/"
_MAX_RESPONSE_BYTES = 4_000_000
_MAX_RSS_ITEMS = 200
_DEFAULT_TIMEOUT_SECONDS = 10
_WAT = ZoneInfo("Africa/Lagos")
_TRUSTED_OFFICIAL_HOSTS = frozenset(
    {
        "federalreserve.gov",
        "www.federalreserve.gov",
        "home.treasury.gov",
        "treasury.gov",
        "www.treasury.gov",
        "bls.gov",
        "www.bls.gov",
        "bea.gov",
        "www.bea.gov",
        "apps.bea.gov",
        "state.gov",
        "www.state.gov",
        "whitehouse.gov",
        "www.whitehouse.gov",
    }
)


class NewsSourceError(RuntimeError):
    """A sanitized source failure. It never contains the request URL or body."""

    def __init__(self, category: str, http_status: int | None = None) -> None:
        super().__init__(category)
        self.category = category
        self.http_status = http_status


@dataclass(frozen=True)
class SourceItem:
    headline: str
    summary: str
    source_name: str
    source_url: str
    published_at: datetime
    retrieved_at: datetime
    tags: tuple[str, ...] = ()
    source_item_id: str | None = None
    event_at: datetime | None = None
    is_discovery_lead: bool = False
    developing: bool = False


@dataclass(frozen=True)
class VerifiedNewsItem:
    item: SourceItem
    verification_status: str
    evidence: tuple[SourceItem, ...] = ()
    verification_reason: str = ""
    item_state: str = "new"
    potential_gold_relevance: str = ""

    @property
    def usable_for_gemini(self) -> bool:
        return self.verification_status == "verified" and bool(self.evidence)


@dataclass(frozen=True)
class EconomicEvent:
    external_id: str
    title: str
    source_name: str
    source_url: str
    event_at: datetime
    source_timezone: str
    importance: str = "high"
    previous: str | None = None
    forecast: str | None = None
    actual: str | None = None
    status: str = "scheduled"
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.event_at.tzinfo is None or self.retrieved_at.tzinfo is None:
            raise ValueError("Event and retrieval timestamps must be timezone-aware.")
        if self.status not in {"scheduled", "confirmed", "revised", "cancelled"}:
            raise ValueError("Unsupported economic event status.")

    @property
    def event_at_wat(self) -> datetime:
        return self.event_at.astimezone(_WAT)

    def display_value(self, name: str) -> str:
        value = getattr(self, name)
        return str(value) if value not in (None, "") else "Unavailable"


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_headline(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _headline_similarity(left: str, right: str) -> float:
    left_words = set(_canonical_headline(left).split())
    right_words = set(_canonical_headline(right).split())
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / len(left_words | right_words)


def _host_allowed(url: str, allowed_hosts: Iterable[str]) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None
            and parsed.hostname.casefold() in set(allowed_hosts)
        )
    except ValueError:
        return False


def _request_bytes(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urlopen,
) -> tuple[bytes, int]:
    if not _host_allowed(url, allowed_hosts):
        raise NewsSourceError("source_url_not_allowlisted")
    request = Request(
        url,
        data=body,
        headers={
            "Accept": "application/json, application/rss+xml, application/xml, text/xml",
            "User-Agent": "SmartMoneyHubNewsResearch/1.0",
            **(headers or {}),
        },
        method=method,
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            status = int(getattr(response, "status", 200))
    except HTTPError as error:
        category = {
            401: "authentication_error",
            403: "permission_error",
            404: "not_found",
            429: "rate_limit",
            503: "service_unavailable",
        }.get(int(error.code), "http_error")
        logger.warning(
            "News source request failed category=%s status=%s.",
            category,
            error.code,
        )
        raise NewsSourceError(category, int(error.code)) from None
    except (TimeoutError, socket.timeout):
        raise NewsSourceError("timeout") from None
    except URLError as error:
        reason = error.reason
        category = (
            "timeout"
            if isinstance(reason, (TimeoutError, socket.timeout))
            or "timed out" in str(reason).casefold()
            else "network_error"
        )
        raise NewsSourceError(category) from None
    except OSError as error:
        category = (
            "timeout"
            if isinstance(error, (TimeoutError, socket.timeout))
            or "timed out" in str(error).casefold()
            else "network_error"
        )
        raise NewsSourceError(category) from None
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise NewsSourceError("response_too_large", status)
    if status < 200 or status >= 300:
        raise NewsSourceError("http_error", status)
    return raw, status


def parse_rss_feed(
    body: bytes,
    *,
    source_name: str,
    source_url: str,
    retrieved_at: datetime | None = None,
    tags: tuple[str, ...] = (),
) -> list[SourceItem]:
    """Parse RSS/Atom-like official feeds without treating feed presence as proof."""
    if not _host_allowed(source_url, _TRUSTED_OFFICIAL_HOSTS):
        raise NewsSourceError("source_url_not_allowlisted")
    retrieved = retrieved_at or datetime.now(timezone.utc)
    if retrieved.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise NewsSourceError("malformed_feed") from None

    entries = root.findall(".//item")
    if not entries:
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    result: list[SourceItem] = []
    for entry in entries[:_MAX_RSS_ITEMS]:
        title = _xml_text(entry, ("title",))
        summary = _xml_text(entry, ("description", "summary", "content"))
        link = _xml_text(entry, ("link",))
        if not link:
            atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
            if atom_link is not None:
                link = atom_link.attrib.get("href", "")
        published = _xml_text(
            entry,
            ("pubDate", "published", "updated", "date"),
        )
        published_at = _parse_datetime(published)
        if not title or not link or not published_at:
            continue
        if not _host_allowed(link, _TRUSTED_OFFICIAL_HOSTS):
            continue
        guid = _xml_text(entry, ("guid", "id")) or None
        result.append(
            SourceItem(
                headline=title[:500],
                summary=summary[:4000],
                source_name=source_name,
                source_url=link,
                published_at=published_at,
                retrieved_at=retrieved.astimezone(timezone.utc),
                tags=tags,
                source_item_id=guid,
            )
        )
    return result


def _xml_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        child = element.find(name)
        if child is None:
            child = element.find(f"{{http://www.w3.org/2005/Atom}}{name}")
        if child is not None:
            value = " ".join("".join(child.itertext()).split())
            if value:
                return value
    return ""


def fetch_fed_press_releases(
    *,
    retrieved_at: datetime | None = None,
    opener: Callable[..., Any] = urlopen,
) -> list[SourceItem]:
    body, _ = _request_bytes(
        FED_PRESS_RELEASES_RSS,
        allowed_hosts=_TRUSTED_OFFICIAL_HOSTS,
        opener=opener,
    )
    return parse_rss_feed(
        body,
        source_name="Federal Reserve",
        source_url=FED_PRESS_RELEASES_RSS,
        retrieved_at=retrieved_at,
        tags=("fed", "usd", "monetary_policy"),
    )


def fetch_treasury_yields(
    year: int,
    *,
    opener: Callable[..., Any] = urlopen,
) -> list[dict[str, str]]:
    """Fetch the official daily Treasury curve; values are observations, not forecasts."""
    if year < 1990 or year > datetime.now(timezone.utc).year + 1:
        raise ValueError("Treasury year is outside the supported range.")
    url = TREASURY_DAILY_YIELDS_URL.format(year=year)
    body, _ = _request_bytes(
        url, allowed_hosts=_TRUSTED_OFFICIAL_HOSTS, opener=opener
    )
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise NewsSourceError("malformed_treasury_response") from None
    rows: list[dict[str, str]] = []
    for entry in root.iter():
        fields = {
            child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
            for child in entry
        }
        day = fields.get("NEW_DATE") or fields.get("new_date")
        if not day:
            continue
        rows.append(
            {
                "date": day,
                "1m": fields.get("BC_1MONTH", ""),
                "3m": fields.get("BC_3MONTH", ""),
                "6m": fields.get("BC_6MONTH", ""),
                "1y": fields.get("BC_1YEAR", ""),
                "2y": fields.get("BC_2YEAR", ""),
                "5y": fields.get("BC_5YEAR", ""),
                "10y": fields.get("BC_10YEAR", ""),
                "20y": fields.get("BC_20YEAR", ""),
                "30y": fields.get("BC_30YEAR", ""),
            }
        )
    return rows


def fetch_bls_series(
    series_ids: list[str],
    *,
    start_year: int,
    end_year: int,
    api_key: str | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Read BLS API v2 observations; caller must supply an API key via Secrets."""
    if not series_ids or len(series_ids) > 50:
        raise ValueError("Provide between 1 and 50 BLS series IDs.")
    if any(not re.fullmatch(r"[A-Z0-9]{8,30}", item) for item in series_ids):
        raise ValueError("BLS series IDs contain unsupported characters.")
    data: dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if api_key:
        data["registrationkey"] = api_key
    raw, _ = _request_bytes(
        BLS_API_V2,
        allowed_hosts={"api.bls.gov"},
        method="POST",
        body=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        opener=opener,
    )
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NewsSourceError("malformed_bls_response") from None
    if not isinstance(result, dict) or result.get("status") != "REQUEST_SUCCEEDED":
        raise NewsSourceError("bls_request_rejected")
    return result


def fetch_bea_data(
    parameters: dict[str, str],
    *,
    api_key: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Read a BEA API query; the key must come from the Replit Secrets flow."""
    if not api_key.strip():
        raise NewsSourceError("bea_key_missing")
    allowed = {
        "method",
        "datasetname",
        "TableName",
        "LineNumber",
        "Year",
        "Frequency",
        "GeoFips",
        "ResultFormat",
    }
    if set(parameters) - allowed:
        raise ValueError("Unsupported BEA query parameter.")
    query = {
        **parameters,
        "UserID": api_key.strip(),
        "ResultFormat": parameters.get("ResultFormat", "JSON"),
    }
    url = f"{BEA_API_DATA}?{urlencode(query)}"
    raw, _ = _request_bytes(
        url, allowed_hosts={"apps.bea.gov"}, opener=opener
    )
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NewsSourceError("malformed_bea_response") from None
    if not isinstance(result, dict) or "BEAAPI" not in result:
        raise NewsSourceError("bea_request_rejected")
    return result


def discover_gdelt_stories(
    query: str,
    *,
    start_date: date,
    end_date: date,
    retrieved_at: datetime | None = None,
    opener: Callable[..., Any] = urlopen,
) -> list[SourceItem]:
    """Use GDELT for discovery only; returned records are unverified leads."""
    clean_query = " ".join(query.split())[:160]
    if not clean_query or end_date < start_date:
        raise ValueError("A query and valid date range are required.")
    params = {
        "query": clean_query,
        "mode": "ArtList",
        "format": "json",
        "sort": "DateDesc",
        "startdatetime": start_date.strftime("%Y%m%d000000"),
        "enddatetime": end_date.strftime("%Y%m%d235959"),
        "maxrecords": "50",
    }
    url = f"{GDELT_DOC_API}?{urlencode(params)}"
    body, _ = _request_bytes(
        url, allowed_hosts={"api.gdeltproject.org"}, opener=opener
    )
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NewsSourceError("malformed_gdelt_response") from None
    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list):
        raise NewsSourceError("gdelt_articles_missing")
    retrieved = retrieved_at or datetime.now(timezone.utc)
    leads: list[SourceItem] = []
    for article in articles[:50]:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        url_value = str(article.get("url") or "").strip()
        published = _parse_datetime(str(article.get("seendate") or ""))
        if not title or not url_value or not published:
            continue
        leads.append(
            SourceItem(
                headline=title[:500],
                summary=str(article.get("domain") or "")[:500],
                source_name="GDELT discovery lead",
                source_url=url_value,
                published_at=published,
                retrieved_at=retrieved.astimezone(timezone.utc),
                tags=("geopolitical", "discovery_lead"),
                source_item_id=str(article.get("url") or "")[:1000],
                is_discovery_lead=True,
            )
        )
    return leads


def verify_discovery_lead(
    lead: SourceItem,
    official_evidence: Iterable[SourceItem],
    *,
    minimum_similarity: float = 0.48,
) -> VerifiedNewsItem:
    """Require a relevant, timestamped, allowlisted official match before use."""
    if not lead.is_discovery_lead:
        raise ValueError("Only discovery leads use this verification function.")
    matches: list[SourceItem] = []
    for evidence in official_evidence:
        if not _host_allowed(evidence.source_url, _TRUSTED_OFFICIAL_HOSTS):
            continue
        if (
            abs((lead.published_at - evidence.published_at).total_seconds())
            <= 14 * 24 * 60 * 60
            and _headline_similarity(lead.headline, evidence.headline)
            >= minimum_similarity
        ):
            matches.append(evidence)
    if not matches:
        return VerifiedNewsItem(
            item=lead,
            verification_status="held",
            verification_reason="No matching official statement or release was found.",
        )
    latest = max(matches, key=lambda item: item.published_at)
    return VerifiedNewsItem(
        item=lead,
        verification_status="verified",
        evidence=(latest,),
        verification_reason="Matched against an allowlisted official source.",
        potential_gold_relevance=(
            "Potential context only; possible effects on gold are uncertain and "
            "must not be treated as a trading signal."
        ),
    )


def convert_event_to_wat(value: datetime, source_timezone: str) -> datetime:
    """Convert a source-local event time to WAT while respecting DST."""
    if value.tzinfo is not None:
        return value.astimezone(_WAT)
    zone = ZoneInfo(source_timezone)
    return value.replace(tzinfo=zone).astimezone(_WAT)


def is_stale(
    retrieved_at: datetime,
    *,
    now: datetime | None = None,
    max_age: int = 6 * 60 * 60,
) -> bool:
    observed = now or datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None or observed.tzinfo is None:
        raise ValueError("Staleness checks require timezone-aware timestamps.")
    age_seconds = (observed - retrieved_at).total_seconds()
    return age_seconds < 0 or age_seconds > max_age


def telegram_html(text: str) -> str:
    """Escape plain text for safe Telegram HTML rendering, preserving line breaks."""
    return html.escape(text, quote=False).replace("\n", "\n")


def build_admin_news_alert(item: VerifiedNewsItem) -> str:
    """Prepare (but do not send) a private admin alert for verified information."""
    if not item.usable_for_gemini:
        raise ValueError("Only verified items with evidence can become alerts.")
    source = item.evidence[0]
    published_wat = item.item.published_at.astimezone(_WAT).strftime(
        "%d %b %Y, %H:%M WAT"
    )
    summary = source.summary or item.item.summary
    text = (
        "📰 <b>VERIFIED NEWS LEAD</b>\n\n"
        f"<b>{html.escape(item.item.headline, quote=False)}</b>\n\n"
        f"{html.escape(summary, quote=False)}\n\n"
        f"Lead published: {published_wat}\n"
        "Verified source published: "
        f"{source.published_at.astimezone(_WAT).strftime('%d %b %Y, %H:%M WAT')}\n"
        f"Source: <a href=\"{html.escape(source.source_url, quote=True)}\">"
        f"{html.escape(source.source_name, quote=False)}</a>\n\n"
        "Gold impact is uncertain; this is context, not an entry signal."
    )
    return text


def build_gold_impact_prompt(items: Iterable[VerifiedNewsItem]) -> str:
    """Build a source-bounded Gemini prompt; unverified leads are excluded."""
    evidence = []
    for index, verified in enumerate(items, 1):
        if not verified.usable_for_gemini:
            continue
        primary = verified.evidence[0]
        evidence.append(
            {
                "id": f"S{index}",
                "headline": primary.headline[:400],
                "summary": primary.summary[:2000],
                "source": primary.source_name,
                "url": primary.source_url,
                "published_at_utc": _utc_iso(primary.published_at),
                "retrieved_at_utc": _utc_iso(primary.retrieved_at),
            }
        )
    if not evidence:
        raise ValueError("No verified source items are available for analysis.")
    return (
        f"MODEL: {GEMINI_MODEL}\n"
        "Explain possible implications of only the supplied verified information "
        "for XAU/USD. Label confirmed facts, expectations, interpretation, and "
        "unknown or conflicting information separately. Cite the supplied source "
        "URLs for confirmed facts. "
        "Do not invent prices, news, expectations, market reactions, or technical "
        "signals. Do not assert a bullish or bearish outcome; describe plausible "
        "opposing effects and uncertainty. News is never technical entry confirmation. "
        "Return concise plain text for administrator review only; it is not publishable "
        "without separate validation and approval.\n"
        f"VERIFIED SOURCES: {json.dumps(evidence, ensure_ascii=False)}"
    )


def build_event_reminder(event: EconomicEvent) -> str:
    """Prepare an advance event reminder; absent values remain explicitly unavailable."""
    if event.status != "scheduled":
        raise ValueError("Advance reminders are only for scheduled events.")
    local = event.event_at_wat.strftime("%a, %d %b %Y at %H:%M WAT")
    return (
        "📅 <b>UPCOMING USD ECONOMIC EVENT</b>\n\n"
        f"<b>{html.escape(event.title, quote=False)}</b>\n"
        f"Time: {local}\n"
        f"Importance: {html.escape(event.importance, quote=False)}\n"
        f"Previous: {html.escape(event.display_value('previous'), quote=False)}\n"
        f"Forecast: {html.escape(event.display_value('forecast'), quote=False)}\n"
        "Actual: Unavailable (event is scheduled, not yet released)\n\n"
        f'Source: <a href="{html.escape(event.source_url, quote=True)}">'
        f"{html.escape(event.source_name, quote=False)}</a>"
    )


def build_release_alert(event: EconomicEvent) -> str:
    """Prepare a release alert only when a source supplied an actual observation."""
    if event.status not in {"confirmed", "revised"} or not event.actual:
        raise ValueError("A release alert requires confirmed actual data.")
    local = event.event_at_wat.strftime("%a, %d %b %Y at %H:%M WAT")
    return (
        "📊 <b>USD ECONOMIC RELEASE</b>\n\n"
        f"<b>{html.escape(event.title, quote=False)}</b>\n"
        f"Release time: {local}\n"
        f"Previous: {html.escape(event.display_value('previous'), quote=False)}\n"
        f"Forecast: {html.escape(event.display_value('forecast'), quote=False)}\n"
        f"Actual: <b>{html.escape(event.display_value('actual'), quote=False)}</b>\n"
        f"Status: {html.escape(event.status, quote=False)}\n\n"
        "Possible gold implications are uncertain and require separate analysis.\n"
        f'Source: <a href="{html.escape(event.source_url, quote=True)}">'
        f"{html.escape(event.source_name, quote=False)}</a>"
    )


def build_macro_section(
    items: Iterable[VerifiedNewsItem],
    *,
    now: datetime | None = None,
) -> str:
    """Create a source-labelled, facts-only macro section from verified records."""
    verified = [
        item for item in items
        if item.usable_for_gemini and not is_stale(item.item.retrieved_at, now=now)
    ]
    if not verified:
        return (
            "🧠 <b>FUNDAMENTAL DRIVERS &amp; MACRO BACKDROP</b>\n\n"
            "No fresh, verified source items are available for this section. "
            "Market facts are omitted rather than estimated."
        )
    lines = ["🧠 <b>FUNDAMENTAL DRIVERS &amp; MACRO BACKDROP</b>"]
    for item in verified[:5]:
        source = item.evidence[0]
        when = source.published_at.astimezone(_WAT).strftime("%d %b %Y, %H:%M WAT")
        lines.extend(
            [
                "",
                f"<b>{html.escape(source.headline, quote=False)}</b>",
                html.escape(source.summary, quote=False),
                f"Published: {when}",
                f'Source: <a href="{html.escape(source.source_url, quote=True)}">'
                f"{html.escape(source.source_name, quote=False)}</a>",
                "Gold implication: uncertain; this is context, not a trade signal.",
            ]
        )
    return "\n".join(lines)


def validate_gold_impact_analysis(text: str, items: Iterable[VerifiedNewsItem]) -> str | None:
    """A conservative structural gate; all passing output still needs admin review."""
    verified = [item for item in items if item.usable_for_gemini]
    if not verified:
        return "no_verified_sources"
    required_sections = ("confirmed facts", "expectations", "interpretation", "unknown")
    normalized = text.casefold()
    if any(section not in normalized for section in required_sections):
        return "analysis_sections_missing"
    urls = {
        evidence.source_url
        for item in verified
        for evidence in item.evidence
    }
    if not any(url in text for url in urls):
        return "source_citation_missing"
    cited_numbers = {
        number
        for item in verified
        for evidence in item.evidence
        for number in re.findall(r"(?<!\w)\d+(?:[.,]\d+)?%?", evidence.summary)
    }
    output_numbers = set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?%?", text))
    if output_numbers - cited_numbers:
        return "unsupported_numeric_claim"
    source_text = " ".join(
        evidence.headline + " " + evidence.summary
        for item in verified
        for evidence in item.evidence
    ).casefold()
    unsupported_live_claims = (
        r"\b(?:gold|xau/?usd)\b.{0,45}\b(?:is trading|traded at|rose|fell|"
        r"surged|slumped|currently|today at|closed at)\b",
        r"\b(?:market|gold)\b.{0,35}\b(?:reacted to|was driven by|moved because)\b",
    )
    for pattern in unsupported_live_claims:
        for match in re.finditer(pattern, text.casefold()):
            if match.group(0) not in source_text:
                return "unsupported_live_market_claim"
    return None


class NewsRepository:
    """SQLite persistence for verified news, source history, events, and analyses."""

    def __init__(self, database_path: str | Path) -> None:
        import sqlite3

        self._sqlite3 = sqlite3
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = self._sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = self._sqlite3.Row
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS news_intelligence_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fingerprint TEXT NOT NULL,
                        headline TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        source_name TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        evidence_json TEXT NOT NULL,
                        published_at_utc TEXT NOT NULL,
                        event_at_utc TEXT,
                        retrieved_at_utc TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        verification_status TEXT NOT NULL CHECK (
                            verification_status IN ('lead', 'verified', 'held', 'conflicting')
                        ),
                        verification_reason TEXT NOT NULL DEFAULT '',
                        item_state TEXT NOT NULL CHECK (
                            item_state IN ('new', 'updated', 'developing', 'already_reported')
                        ),
                        potential_gold_relevance TEXT NOT NULL DEFAULT '',
                        content_hash TEXT NOT NULL,
                        notified_at_utc TEXT,
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS news_items_published
                    ON news_intelligence_items (published_at_utc DESC);
                    CREATE INDEX IF NOT EXISTS news_items_state
                    ON news_intelligence_items (verification_status, item_state);

                    CREATE TABLE IF NOT EXISTS news_economic_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        external_id TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        source_name TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        event_at_utc TEXT NOT NULL,
                        source_timezone TEXT NOT NULL,
                        importance TEXT NOT NULL,
                        previous_value TEXT,
                        forecast_value TEXT,
                        actual_value TEXT,
                        status TEXT NOT NULL CHECK (
                            status IN ('scheduled', 'confirmed', 'revised', 'cancelled')
                        ),
                        retrieved_at_utc TEXT NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS news_events_due
                    ON news_economic_events (event_at_utc, status);

                    CREATE TABLE IF NOT EXISTS news_admin_notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        notification_type TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending' CHECK (
                            status IN ('pending', 'sent', 'failed', 'held')
                        ),
                        created_at_utc TEXT NOT NULL,
                        sent_at_utc TEXT
                    );

                    CREATE TABLE IF NOT EXISTS news_gold_analyses (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dedupe_key TEXT NOT NULL UNIQUE,
                        source_ids_json TEXT NOT NULL,
                        model TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (
                            status IN ('awaiting_admin_review', 'held', 'approved')
                        ),
                        analysis_text TEXT,
                        failure_category TEXT,
                        created_at_utc TEXT NOT NULL
                    );
                    """
                )
        finally:
            connection.close()

    def save_news_item(self, item: VerifiedNewsItem) -> dict[str, Any]:
        """Persist an item, distinguishing duplicates from changed/revised stories."""
        now = datetime.now(timezone.utc)
        headline_key = _canonical_headline(item.item.headline)
        fingerprint = hashlib.sha256(headline_key.encode("utf-8")).hexdigest()
        content_hash = hashlib.sha256(
            (item.item.headline + "\n" + item.item.summary).encode("utf-8")
        ).hexdigest()
        evidence_json = json.dumps(
            [asdict(evidence) | {
                "published_at": _utc_iso(evidence.published_at),
                "retrieved_at": _utc_iso(evidence.retrieved_at),
                "event_at": _utc_iso(evidence.event_at) if evidence.event_at else None,
            } for evidence in item.evidence],
            ensure_ascii=False,
        )
        connection = self._connect()
        try:
            with connection:
                rows = connection.execute(
                    """
                    SELECT * FROM news_intelligence_items
                    WHERE created_at_utc >= ? ORDER BY created_at_utc DESC LIMIT 300
                    """,
                    (_utc_iso(now - timedelta(days=366)),),
                ).fetchall()
                matched = next(
                    (
                        row for row in rows
                        if row["fingerprint"] == fingerprint
                        or _headline_similarity(row["headline"], item.item.headline) >= 0.78
                    ),
                    None,
                )
                published = _utc_iso(item.item.published_at)
                event_at = _utc_iso(item.item.event_at) if item.item.event_at else None
                retrieved = _utc_iso(item.item.retrieved_at)
                if matched:
                    if matched["content_hash"] == content_hash:
                        saved_id = int(matched["id"])
                        if (
                            item.verification_status == "verified"
                            and matched["verification_status"] != "verified"
                        ):
                            connection.execute(
                                """
                                UPDATE news_intelligence_items
                                SET evidence_json = ?, verification_status = ?,
                                    verification_reason = ?, item_state = ?,
                                    potential_gold_relevance = ?, retrieved_at_utc = ?,
                                    updated_at_utc = ?
                                WHERE id = ?
                                """,
                                (
                                    evidence_json,
                                    item.verification_status,
                                    item.verification_reason,
                                    "developing" if item.item.developing else "updated",
                                    item.potential_gold_relevance,
                                    retrieved,
                                    _utc_iso(now),
                                    matched["id"],
                                ),
                            )
                            state = "developing" if item.item.developing else "updated"
                        else:
                            connection.execute(
                                """
                                UPDATE news_intelligence_items
                                SET item_state = 'already_reported',
                                    retrieved_at_utc = ?, updated_at_utc = ?
                                WHERE id = ?
                                """,
                                (retrieved, _utc_iso(now), matched["id"]),
                            )
                            state = "already_reported"
                    else:
                        connection.execute(
                            """
                            UPDATE news_intelligence_items
                            SET headline = ?, summary = ?, source_name = ?, source_url = ?,
                                evidence_json = ?, published_at_utc = ?, event_at_utc = ?,
                                retrieved_at_utc = ?, tags_json = ?,
                                verification_status = ?, verification_reason = ?,
                                item_state = ?, potential_gold_relevance = ?,
                                content_hash = ?, updated_at_utc = ?
                            WHERE id = ?
                            """,
                            (
                                item.item.headline,
                                item.item.summary,
                                item.item.source_name,
                                item.item.source_url,
                                evidence_json,
                                published,
                                event_at,
                                retrieved,
                                json.dumps(item.item.tags),
                                item.verification_status,
                                item.verification_reason,
                                "developing" if item.item.developing else "updated",
                                item.potential_gold_relevance,
                                content_hash,
                                _utc_iso(now),
                                matched["id"],
                            ),
                        )
                        saved_id = int(matched["id"])
                        state = "developing" if item.item.developing else "updated"
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO news_intelligence_items (
                            fingerprint, headline, summary, source_name, source_url,
                            evidence_json, published_at_utc, event_at_utc,
                            retrieved_at_utc, tags_json, verification_status,
                            verification_reason, item_state, potential_gold_relevance,
                            content_hash, created_at_utc, updated_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fingerprint,
                            item.item.headline,
                            item.item.summary,
                            item.item.source_name,
                            item.item.source_url,
                            evidence_json,
                            published,
                            event_at,
                            retrieved,
                            json.dumps(item.item.tags),
                            item.verification_status,
                            item.verification_reason,
                            item.item_state,
                            item.potential_gold_relevance,
                            content_hash,
                            _utc_iso(now),
                            _utc_iso(now),
                        ),
                    )
                    saved_id = int(cursor.lastrowid)
                    state = item.item_state
                saved = connection.execute(
                    "SELECT * FROM news_intelligence_items WHERE id = ?",
                    (saved_id,),
                ).fetchone()
                result = dict(saved)
                result["item_state"] = state
                return result
        finally:
            connection.close()

    def save_event(self, event: EconomicEvent) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        connection = self._connect()
        try:
            with connection:
                prior = connection.execute(
                    "SELECT * FROM news_economic_events WHERE external_id = ?",
                    (event.external_id,),
                ).fetchone()
                status = event.status
                if prior and any(
                    prior[column] != value
                    for column, value in (
                        ("event_at_utc", _utc_iso(event.event_at)),
                        ("previous_value", event.previous),
                        ("forecast_value", event.forecast),
                        ("actual_value", event.actual),
                    )
                ) and event.status != "cancelled":
                    status = "revised"
                values = (
                    event.title,
                    event.source_name,
                    event.source_url,
                    _utc_iso(event.event_at),
                    event.source_timezone,
                    event.importance,
                    event.previous,
                    event.forecast,
                    event.actual,
                    status,
                    _utc_iso(event.retrieved_at),
                    _utc_iso(now),
                )
                if prior:
                    connection.execute(
                        """
                        UPDATE news_economic_events SET title=?, source_name=?,
                            source_url=?, event_at_utc=?, source_timezone=?,
                            importance=?, previous_value=?, forecast_value=?,
                            actual_value=?, status=?, retrieved_at_utc=?,
                            updated_at_utc=? WHERE external_id=?
                        """,
                        (*values, event.external_id),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO news_economic_events (
                            external_id, title, source_name, source_url, event_at_utc,
                            source_timezone, importance, previous_value, forecast_value,
                            actual_value, status, retrieved_at_utc, created_at_utc,
                            updated_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.external_id,
                            *values[:11],
                            _utc_iso(now),
                            values[11],
                        ),
                    )
                row = connection.execute(
                    "SELECT * FROM news_economic_events WHERE external_id = ?",
                    (event.external_id,),
                ).fetchone()
                return dict(row)
        finally:
            connection.close()

    def enqueue_notification(
        self,
        dedupe_key: str,
        notification_type: str,
        payload: str,
        *,
        status: str = "pending",
    ) -> bool:
        if status not in {"pending", "sent", "failed", "held"}:
            raise ValueError("Invalid notification state.")
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO news_admin_notifications (
                        dedupe_key, notification_type, payload, status, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        dedupe_key,
                        notification_type,
                        payload,
                        status,
                        _utc_iso(datetime.now(timezone.utc)),
                    ),
                )
                return cursor.rowcount == 1
        finally:
            connection.close()

    def list_news_items(
        self,
        *,
        verified_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            query = "SELECT * FROM news_intelligence_items"
            values: tuple[Any, ...] = ()
            if verified_only:
                query += " WHERE verification_status = 'verified'"
            query += " ORDER BY published_at_utc DESC LIMIT ?"
            values = (max(1, min(int(limit), 200)),)
            return [dict(row) for row in connection.execute(query, values).fetchall()]
        finally:
            connection.close()

    def list_events(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if start_at.tzinfo is None or end_at.tzinfo is None:
            raise ValueError("Calendar range must be timezone-aware.")
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM news_economic_events
                WHERE event_at_utc >= ? AND event_at_utc <= ?
                  AND status != 'cancelled'
                ORDER BY event_at_utc ASC LIMIT ?
                """,
                (
                    _utc_iso(start_at),
                    _utc_iso(end_at),
                    max(1, min(int(limit), 500)),
                ),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def mark_notification_sent(
        self, notification_id: int, *, sent_at: datetime | None = None
    ) -> bool:
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE news_admin_notifications
                    SET status = 'sent', sent_at_utc = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (_utc_iso(sent_at or datetime.now(timezone.utc)), notification_id),
                )
                return cursor.rowcount == 1
        finally:
            connection.close()

    def list_pending_notifications(self, *, limit: int = 50) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM news_admin_notifications
                WHERE status = 'pending' ORDER BY id ASC LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def save_analysis(
        self,
        *,
        dedupe_key: str,
        source_ids: list[int],
        analysis_text: str | None,
        failure_category: str | None = None,
    ) -> bool:
        status = "held" if failure_category else "awaiting_admin_review"
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO news_gold_analyses (
                        dedupe_key, source_ids_json, model, status, analysis_text,
                        failure_category, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dedupe_key,
                        json.dumps(source_ids),
                        GEMINI_MODEL,
                        status,
                        analysis_text,
                        failure_category,
                        _utc_iso(datetime.now(timezone.utc)),
                    ),
                )
                return cursor.rowcount == 1
        finally:
            connection.close()


class GeminiGoldImpactAnalyzer:
    """One-model-only Gemini analysis of verified facts; never publishes directly."""

    model = GEMINI_MODEL

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 12,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def analyze(self, items: Iterable[VerifiedNewsItem]) -> str:
        verified_items = [item for item in items if item.usable_for_gemini]
        prompt = build_gold_impact_prompt(verified_items)
        if not self._api_key:
            raise NewsSourceError("gemini_not_configured")
        request_id = uuid.uuid4().hex
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent"
        )
        payload = {
            "systemInstruction": {
                "parts": [{
                    "text": (
                        "You are a cautious macro educator. Separate source-confirmed "
                        "facts from interpretation, market expectations, and unknowns. "
                        "Use only facts supplied in the user content; cite source URLs "
                        "for facts. Gold effects can oppose each other; never state a "
                        "direction as certain, invent live prices/news, or imply an "
                        "entry signal. Output sections exactly: CONFIRMED FACTS, "
                        "EXPECTATIONS, INTERPRETATION FOR XAU/USD, UNKNOWN OR CONFLICTING."
                    )
                }]
            },
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500},
        }
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            logger.warning(
                "Gold impact analysis failed category=%s status=%s elapsed_ms=%s "
                "request_id=%s.",
                "rate_limit" if error.code == 429 else "provider_error",
                error.code,
                int((time.monotonic() - started) * 1000),
                request_id,
            )
            raise NewsSourceError(
                "gemini_rate_limit" if error.code == 429 else "gemini_provider_error",
                int(error.code),
            ) from None
        except (TimeoutError, socket.timeout):
            raise NewsSourceError("gemini_timeout") from None
        except URLError as error:
            category = (
                "gemini_timeout"
                if isinstance(error.reason, (TimeoutError, socket.timeout))
                else "gemini_network_error"
            )
            raise NewsSourceError(category) from None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            raise NewsSourceError("gemini_invalid_response") from None

        try:
            candidate = data["candidates"][0]
            finish = candidate.get("finishReason")
            parts = candidate["content"]["parts"]
            text = "\n".join(
                part["text"]
                for part in parts
                if isinstance(part, dict)
                and isinstance(part.get("text"), str)
                and part.get("thought") is not True
            ).strip()
        except (KeyError, IndexError, TypeError):
            raise NewsSourceError("gemini_missing_text") from None
        logger.info(
            "Gold impact response received status=%s finish_reason=%s elapsed_ms=%s "
            "request_id=%s.",
            status,
            finish or "missing",
            int((time.monotonic() - started) * 1000),
            request_id,
        )
        if finish != "STOP":
            raise NewsSourceError(
                "gemini_max_tokens" if finish == "MAX_TOKENS" else "gemini_finish_rejected",
                status,
            )
        if not text:
            raise NewsSourceError("gemini_missing_text", status)
        rejection = validate_gold_impact_analysis(text, verified_items)
        if rejection:
            raise NewsSourceError(rejection, status)
        return text


class NewsIntelligencePipeline:
    """Persistence and preview orchestration; it does not publish to channels."""

    def __init__(self, repository: NewsRepository) -> None:
        self.repository = repository

    def process_discovery_leads(
        self,
        leads: Iterable[SourceItem],
        official_evidence: Iterable[SourceItem],
    ) -> list[dict[str, Any]]:
        evidence = list(official_evidence)
        results: list[dict[str, Any]] = []
        for lead in leads:
            verified = verify_discovery_lead(lead, evidence)
            saved = self.repository.save_news_item(verified)
            if verified.usable_for_gemini:
                alert = build_admin_news_alert(verified)
                dedupe_key = hashlib.sha256(
                    (
                        "news:"
                        + str(saved["id"])
                        + ":"
                        + str(saved["content_hash"])
                    ).encode("utf-8")
                ).hexdigest()
                self.repository.enqueue_notification(
                    dedupe_key, "verified_news", alert
                )
            results.append(saved)
        return results

    def record_source_failure(
        self, source_name: str, error: NewsSourceError
    ) -> bool:
        """Queue a sanitized admin notice; no source URL, body, or secret is retained."""
        category = re.sub(r"[^a-z0-9_]", "", error.category.casefold())[:60]
        payload = (
            f"News source unavailable: {source_name}. "
            f"Failure category: {category or 'unknown'}."
        )
        key = hashlib.sha256(
            f"source_failure:{source_name}:{category}:{datetime.now(timezone.utc).date()}".encode()
        ).hexdigest()
        return self.repository.enqueue_notification(
            key, "source_failure", payload, status="pending"
        )

    def record_gemini_analysis(
        self,
        *,
        dedupe_key: str,
        source_ids: list[int],
        text: str,
        items: list[VerifiedNewsItem],
    ) -> bool:
        rejection = validate_gold_impact_analysis(text, items)
        return self.repository.save_analysis(
            dedupe_key=dedupe_key,
            source_ids=source_ids,
            analysis_text=None if rejection else text,
            failure_category=rejection,
        )


def sample_treasury_macro_alert(
    observation_date: str,
    values: dict[str, str],
    previous_values: dict[str, str],
    source_url: str,
) -> str:
    """Format only supplied Treasury observations; never infer missing readings."""
    key_dates = date.fromisoformat(observation_date).strftime("%d %b %Y")
    lines = [
        "📊 <b>U.S. TREASURY YIELD UPDATE</b>",
        f"Observation date: {key_dates}",
    ]
    for key, label in (("2y", "2-year"), ("10y", "10-year"), ("30y", "30-year")):
        current = values.get(key) or "Unavailable"
        prior = previous_values.get(key)
        change = "change unavailable"
        if current != "Unavailable" and prior:
            try:
                delta = float(current) - float(prior)
                change = f"{delta:+.2f} percentage points vs prior observation"
            except ValueError:
                change = "change unavailable"
        lines.append(f"{label}: {html.escape(current)}% ({change})")
    lines.extend(
        [
            "",
            "Yield changes can be one part of gold-market context; they do not "
            "establish a direction or provide technical entry confirmation.",
            f'Source: <a href="{html.escape(source_url, quote=True)}">U.S. Treasury</a>',
        ]
    )
    return "\n".join(lines)


__all__ = [
    "BEA_API_DATA",
    "BLS_API_V2",
    "EconomicEvent",
    "GeminiGoldImpactAnalyzer",
    "NewsRepository",
    "NewsSourceError",
    "SourceItem",
    "VerifiedNewsItem",
    "build_admin_news_alert",
    "build_event_reminder",
    "build_gold_impact_prompt",
    "build_macro_section",
    "build_release_alert",
    "convert_event_to_wat",
    "discover_gdelt_stories",
    "fetch_bea_data",
    "fetch_bls_series",
    "fetch_fed_press_releases",
    "fetch_treasury_yields",
    "is_stale",
    "parse_rss_feed",
    "sample_treasury_macro_alert",
    "telegram_html",
    "validate_gold_impact_analysis",
    "verify_discovery_lead",
]
