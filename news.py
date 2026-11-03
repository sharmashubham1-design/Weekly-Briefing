"""Free, source-backed daily briefing builder.

The module deliberately uses no generative model. It reads a small, fixed set of
public RSS/Atom feeds, preserves the source language, and adds only transparent
classification and educational context.
"""

from __future__ import annotations

import hashlib
import html
import csv
import io
import re
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from db import TOPICS


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str
    topic: str | None = None
    official: bool = False
    kind: str = "news"


SOURCES = (
    FeedSource("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "Markets & investing", True, "macro"),
    FeedSource("SEC policy", "https://www.sec.gov/news/pressreleases.rss", "Markets & investing", True, "policy"),
    FeedSource("SEC 8-K filings", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&owner=include&count=40&output=atom", "Markets & investing", True, "filing"),
    FeedSource("SEC insider filings", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=include&count=40&output=atom", "Markets & investing", True, "filing"),
    FeedSource("BLS employment", "https://www.bls.gov/feed/empsit.rss", "Markets & investing", True, "macro"),
    FeedSource("BLS inflation", "https://www.bls.gov/feed/cpi.rss", "Markets & investing", True, "macro"),
    FeedSource("BEA economics", "https://apps.bea.gov/rss/rss.xml", "Markets & investing", True, "macro"),
    FeedSource("EIA energy", "https://www.eia.gov/rss/todayinenergy.xml", "Markets & investing", True, "macro"),
    FeedSource("CFPB", "https://www.consumerfinance.gov/about-us/blog/feed/", "Real estate & mortgages", True, "policy"),
    FeedSource("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", kind="news"),
    FeedSource("NPR Business", "https://feeds.npr.org/1006/rss.xml", kind="news"),
    FeedSource("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", "Tech, AI & industry", False, "tech"),
    FeedSource("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "Tech, AI & industry", False, "tech"),
)

REFERENCE_BOARD = (
    {"name": "Fed calendar & FOMC", "cadence": "Every morning; live on decision days", "why": "Policy decisions, minutes and speeches can reset the rates path.", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "lag": "Scheduled/official"},
    {"name": "BLS release calendar", "cadence": "Every morning", "why": "Know when CPI, payrolls, JOLTS, PPI and wages can move expectations.", "url": "https://www.bls.gov/schedule/", "lag": "Scheduled/official"},
    {"name": "BEA release schedule", "cadence": "Every morning", "why": "GDP, PCE inflation, income and spending are core macro inputs.", "url": "https://www.bea.gov/news/schedule", "lag": "Scheduled/official"},
    {"name": "Treasury yield curve", "cadence": "After each U.S. business-day close", "why": "Rates and curve shape affect discount rates, financing costs and regime views.", "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve", "lag": "Daily closing indications"},
    {"name": "SEC latest filings", "cadence": "Morning, midday and after close", "why": "8-K, 10-Q/10-K, Form 4 and 13D/G can change a company thesis.", "url": "https://www.sec.gov/search-filings", "lag": "Near publication; form-dependent"},
    {"name": "CFTC Commitments of Traders", "cadence": "On release; review weekly", "why": "Shows aggregate positioning across major futures markets.", "url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm", "lag": "Usually Friday for Tuesday positions"},
)

FINANCE_RELEVANCE = (
    "stock", "share", "market", "invest", "earnings", "revenue", "profit", "guidance", "bond", "yield",
    "inflation", "jobs", "employment", "wage", "fed", "interest rate", "econom", "gdp", "bank", "credit",
    "oil", "gas", "commodity", "bitcoin", "crypto", "treasury", "sec ", "fund", "trade", "tariff", "merger",
    "acquisition", "ipo", "housing", "mortgage", "rent", "property", "insurance", "consumer", "spending",
    "artificial intelligence", " ai ", "chip", "semiconductor", "software", "cloud", "data center", "cyber",
    "nvidia", "apple", "google", "microsoft", "amazon", "meta", "tesla",
)

TECH_RELEVANCE = (
    "artificial intelligence", " ai ", "chip", "semiconductor", "software", "cloud", "data center", "cyber",
    "startup", "venture", "funding", "revenue", "profit", "earnings", "antitrust", "regulation", "nvidia",
    "apple", "google", "microsoft", "amazon", "meta", "tesla", "openai", "anthropic",
)

MARKET_SERIES = {
    "SP500": ("S&P 500", "index"),
    "NASDAQCOM": ("Nasdaq Composite", "index"),
    "DGS2": ("2-year Treasury", "yield"),
    "DGS10": ("10-year Treasury", "yield"),
    "VIXCLS": ("VIX", "level"),
    "DCOILWTICO": ("WTI crude", "price"),
}

REDDIT_FEED_URL = "https://www.reddit.com/r/investing+wallstreetbets+stocks+SecurityAnalysis/new/.rss?limit=50"
REDDIT_COMMUNITIES = {
    "investing": "r/investing",
    "wallstreetbets": "r/wallstreetbets",
    "stocks": "r/stocks",
    "securityanalysis": "r/SecurityAnalysis",
}
SENTIMENT_THEMES = {
    "Rates & macro": ("fed", "rate", "inflation", "jobs", "recession", "treasury", "yield", "economy", "gdp"),
    "AI & semiconductors": (" ai ", "artificial intelligence", "nvidia", "nvda", "chip", "semiconductor", "data center"),
    "Mega-cap technology": ("apple", "aapl", "microsoft", "msft", "amazon", "amzn", "google", "googl", "meta", "tesla", "tsla"),
    "Crypto & speculative risk": ("bitcoin", "btc", "crypto", "ethereum", "eth", "meme", "squeeze", "calls", "puts"),
    "Earnings & valuation": ("earnings", "revenue", "guidance", "valuation", "overvalued", "undervalued", "p/e", "cash flow"),
    "Energy & commodities": ("oil", "gas", "energy", "gold", "silver", "commodity", "uranium"),
    "Banks & credit": ("bank", "credit", "loan", "default", "financial", "mortgage"),
}
SENTIMENT_POSITIVE = ("bull", "buy", "rally", "upside", "beat", "breakout", "long", "growth", "ath", "moon", "squeeze", "calls")
SENTIMENT_NEGATIVE = ("bear", "sell", "crash", "downside", "miss", "bubble", "recession", "overvalued", "short", "dump", "puts")

TOPIC_KEYWORDS = {
    "Markets & investing": (
        "stock", "shares", "market", "investor", "earnings", "revenue", "profit", "bond", "yield",
        "inflation", "jobs", "employment", "fed", "interest rate", "economy", "gdp", "bank", "oil",
        "bitcoin", "crypto", "treasury", "sec ", "fund", "trade", "tariff",
    ),
    "Real estate & mortgages": (
        "home", "housing", "mortgage", "property", "rent", "rental", "real estate", "builder",
        "construction", "foreclosure", "refinanc", "consumer finance", "credit score",
    ),
    "Tech, AI & industry": (
        "technology", "tech", "artificial intelligence", " ai ", "chip", "semiconductor", "software",
        "cloud", "robot", "data center", "cyber", "startup", "openai", "anthropic", "apple", "google",
        "microsoft", "amazon", "meta", "tesla", "nvidia",
    ),
}

THEMES = {
    "Rates and borrowing costs": ("interest rate", "mortgage", "yield", "borrowing", "refinanc", "fed"),
    "Inflation and household costs": ("inflation", "prices", "consumer price", "cost of living", "tariff"),
    "Jobs and income": ("jobs", "employment", "unemployment", "wage", "hiring", "layoff"),
    "Housing and affordability": ("housing", "home", "mortgage", "rent", "property"),
    "AI investment and economics": (" ai ", "artificial intelligence", "chip", "data center", "nvidia"),
    "Earnings and business health": ("earnings", "revenue", "profit", "sales", "guidance"),
    "Rules and disclosures": ("sec ", "regulation", "rule", "disclosure", "enforcement"),
}

CONCEPTS = (
    (("interest rate", "yield", "bond", "mortgage", "fed"), "Rate transmission", "How a policy or market-rate change travels into borrowing costs, asset prices and demand."),
    (("inflation", "prices", "consumer price"), "Real purchasing power", "What income can buy after accounting for changes in prices."),
    (("jobs", "employment", "unemployment", "wage"), "Labour-market signal", "A data point that helps show whether demand for workers and wage pressure are strengthening or weakening."),
    (("earnings", "revenue", "profit", "sales"), "Earnings quality", "How much reported profit is supported by repeatable revenue and cash generation rather than one-off effects."),
    (("home", "housing", "mortgage", "rent"), "Housing affordability", "The combined effect of prices, financing costs, income, taxes, insurance and maintenance."),
    ((" ai ", "artificial intelligence", "software", "chip", "cloud"), "Unit economics", "The revenue and variable cost associated with serving one customer or unit of demand."),
    (("sec ", "rule", "regulation", "disclosure"), "Disclosure lag", "The delay between an event or position and when reliable public information becomes available."),
)


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node, names):
    names = set(names)
    for child in list(node):
        if _local(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _clean(value, limit=1200):
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parse_date(value, fallback):
    if not value:
        return fallback
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed(data, source, now=None):
    """Parse RSS or Atom bytes into a small normalized list."""
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(data)
    rows = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = _clean(_child_text(node, ("title",)), 260)
        link = _child_text(node, ("link", "guid"))
        if not link:
            for child in list(node):
                if _local(child.tag) == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        description = _clean(_child_text(node, ("description", "summary", "content", "encoded")))
        published_raw = _child_text(node, ("pubdate", "published", "updated", "date"))
        published = _parse_date(published_raw, None)
        if published is None:
            continue
        if not title or urlparse(link).scheme not in ("http", "https"):
            continue
        rows.append({
            "title": title,
            "url": link,
            "summary": description,
            "published": published,
            "source": source.name,
            "fixed_topic": source.topic,
            "official": source.official,
            "source_kind": source.kind,
        })
    return rows


def fetch_feed(source, timeout=8):
    request = urllib.request.Request(source.url, headers={
        "User-Agent": "MondayBriefing/2.0 (personal financial-literacy reader)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.2",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("Feed exceeded 2 MB safety limit")
        return data


def fetch_market_snapshot(timeout=15):
    """Read delayed daily market observations from the Federal Reserve's FRED export."""
    series = ",".join(MARKET_SERIES)
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    request = urllib.request.Request(url, headers={"User-Agent": "MondayBriefing/2.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(3_000_001)
    if len(raw) > 3_000_000:
        raise ValueError("Market-data response exceeded 3 MB safety limit")
    files = {}
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = {name: archive.read(name) for name in archive.namelist() if name.endswith(".csv")}
    else:
        files = {"fred.csv": raw}
    observations = {series_id: [] for series_id in MARKET_SERIES}
    for data in files.values():
        for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
            date = row.get("observation_date", "")
            for series_id in MARKET_SERIES:
                value = row.get(series_id, "")
                if value not in (None, "", "."):
                    try:
                        observations[series_id].append((date, float(value)))
                    except ValueError:
                        pass
    result = []
    for series_id, (label, value_kind) in MARKET_SERIES.items():
        values = observations[series_id]
        if not values:
            continue
        current_date, current = values[-1]
        prior = values[-2][1] if len(values) > 1 else current
        if value_kind in ("index", "price"):
            change = ((current / prior) - 1) * 100 if prior else 0
            change_text = f"{change:+.2f}% vs prior observation"
            value_text = f"{current:,.2f}"
        elif value_kind == "yield":
            change_text = f"{(current - prior) * 100:+.0f} bp vs prior observation"
            value_text = f"{current:.2f}%"
        else:
            change_text = f"{current - prior:+.2f} vs prior observation"
            value_text = f"{current:.2f}"
        result.append({"id": series_id, "name": label, "value": value_text,
                       "change": change_text, "as_of": current_date,
                       "url": f"https://fred.stlouisfed.org/series/{series_id}"})
    return result


def fetch_reddit_sentiment(timeout=12, data=None, now=None):
    """Summarize titles from one low-frequency, public Reddit RSS request."""
    now = now or datetime.now(timezone.utc)
    if data is None:
        request = urllib.request.Request(REDDIT_FEED_URL, headers={
            "User-Agent": "MondayBriefing/3.0 by u/sharmashubham1-design",
            "Accept": "application/atom+xml, application/rss+xml, text/xml;q=0.9",
        })
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("Reddit feed exceeded 1 MB safety limit")
    rows = parse_feed(data, FeedSource("Reddit communities", REDDIT_FEED_URL, kind="sentiment"), now)
    posts = []
    cutoff = now - timedelta(days=3)
    excluded = ("daily discussion", "weekly discussion", "what are your moves", "rate my portfolio", "beginner questions")
    for row in rows:
        match = re.search(r"/r/([^/]+)/", row["url"], flags=re.I)
        community_key = match.group(1).lower() if match else ""
        if community_key not in REDDIT_COMMUNITIES or row["published"] < cutoff:
            continue
        if any(phrase in row["title"].lower() for phrase in excluded):
            continue
        posts.append({
            "title": row["title"], "url": row["url"],
            "community": REDDIT_COMMUNITIES[community_key],
            "published_at": row["published"].isoformat(),
        })
    posts = posts[:30]
    if not posts:
        raise RuntimeError("No recent Reddit discussion titles were available")

    theme_rows = []
    for label, words in SENTIMENT_THEMES.items():
        matches = [post for post in posts if any(word in f" {post['title'].lower()} " for word in words)]
        if matches:
            communities = sorted({post["community"] for post in matches})
            theme_rows.append({
                "theme": label, "mentions": len(matches),
                "takeaway": f"Discussion is clustering around {label.lower()} across {', '.join(communities)}. Treat this as attention, not evidence.",
                "posts": matches[:2],
            })
    theme_rows.sort(key=lambda row: row["mentions"], reverse=True)
    if len(theme_rows) < 3:
        used = {post["url"] for theme in theme_rows for post in theme["posts"]}
        for post in posts:
            if post["url"] in used:
                continue
            theme_rows.append({
                "theme": "Active single-name discussion", "mentions": 1,
                "takeaway": "A specific company or trade is drawing attention, but one popular thread is not a market-wide signal.",
                "posts": [post],
            })
            used.add(post["url"])
            if len(theme_rows) == 3:
                break

    titles = " ".join(post["title"].lower() for post in posts)
    positive = sum(titles.count(word) for word in SENTIMENT_POSITIVE)
    negative = sum(titles.count(word) for word in SENTIMENT_NEGATIVE)
    total = positive + negative
    score = round(100 * (positive - negative) / total) if total else 0
    label = "Risk-on chatter" if score >= 25 else "Cautious chatter" if score <= -25 else "Mixed chatter"
    community_counts = []
    for name in REDDIT_COMMUNITIES.values():
        count = sum(post["community"] == name for post in posts)
        if count:
            community_counts.append({"name": name, "posts": count, "url": f"https://www.reddit.com/{name}/"})
    return {
        "status": "available", "label": label, "score": score,
        "as_of": now.isoformat(), "post_count": len(posts),
        "confidence": "low" if len(posts) < 12 else "medium",
        "themes": theme_rows[:3], "communities": community_counts,
        "method": "Title-only lexical pulse from one public Reddit RSS request. No comments, user profiles or private data are collected.",
        "caveat": "Reddit communities are self-selected and can be promotional, ironic or coordinated. This measures attention and tone—not investor positioning or expected returns.",
        "cached": False,
    }


def _topic(row):
    if row.get("fixed_topic") in TOPICS:
        return row["fixed_topic"]
    haystack = f" {row['title']} {row.get('summary', '')} ".lower()
    scores = {topic: sum(1 for word in words if word in haystack) for topic, words in TOPIC_KEYWORDS.items()}
    return max(scores, key=scores.get) if max(scores.values()) else "Markets & investing"


def _is_relevant(row):
    """Keep primary market inputs, but make broad editorial feeds earn inclusion."""
    if row.get("official") or row.get("source_kind") in ("macro", "filing", "policy"):
        return True
    haystack = f" {row['title']} {row.get('summary', '')} ".lower()
    words = TECH_RELEVANCE if row.get("source_kind") == "tech" else FINANCE_RELEVANCE
    return any(word in haystack for word in words)


def _theme(row):
    haystack = f" {row['title']} {row.get('summary', '')} ".lower()
    scored = [(sum(1 for word in words if word in haystack), name) for name, words in THEMES.items()]
    score, name = max(scored)
    return name if score else "Business and policy"


def _concept(row):
    haystack = f" {row['title']} {row.get('summary', '')} ".lower()
    for words, term, definition in CONCEPTS:
        if any(word in haystack for word in words):
            return term, definition
    return "Evidence quality", "The reliability, timeliness and directness of the information supporting a claim."


def _id(prefix, value):
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _sentence_summary(row):
    summary = row.get("summary", "")
    if summary:
        sentences = re.split(r"(?<=[.!?])\s+", summary)
        summary = " ".join(sentences[:2])
    return _clean(summary or f"{row['source']} published this update: {row['title']}", 520)


def _why_it_matters(topic):
    return {
        "Markets & investing": "Use it to update your view of rates, inflation, earnings or risk appetite—then separate the source facts from the market’s reaction.",
        "Real estate & mortgages": "It may change the context for borrowing costs, affordability, housing supply or household cash flow.",
        "Tech, AI & industry": "Look for evidence about adoption, competition, capital spending and durable economics—not just product claims.",
    }[topic]


def _watch_next(source_kind):
    return {
        "macro": "Watch the next official release and whether rates react in the same direction.",
        "policy": "Read the primary document and check the effective date and affected entities.",
        "filing": "Open the filing and compare the new disclosure with the prior period.",
        "tech": "Look for confirmation in revenue, margins, capex or a company filing.",
    }.get(source_kind, "Look for a second primary source or company disclosure that confirms the claim.")


def _rank(row, now, interests):
    age_hours = max(0, (now - row["published"]).total_seconds() / 3600)
    freshness = max(0, 7 - age_hours / 24)
    official = 3 if row.get("official") else 0
    topic_interest = 2 * interests.get(row["topic"], .5)
    detail = min(len(row.get("summary", "")) / 300, 1)
    return freshness + official + topic_interest + detail


def _decision_rank(row, now, interests):
    haystack = f" {row['title']} {row.get('summary', '')} ".lower()
    decision_words = (
        "earnings", "guidance", "revenue", "profit", "fed", "rate", "inflation", "jobs", "treasury",
        "yield", "merger", "acquisition", "regulation", "sec ", "tax", "credit", "oil", "bitcoin",
        "semiconductor", "tariff", "gdp", "consumer spending",
    )
    primary_bonus = 4 if row.get("source_kind") in ("macro", "policy", "filing") else 0
    return _rank(row, now, interests) + primary_bonus + 1.5 * sum(word in haystack for word in decision_words)


def _edition(now, tz_name):
    local = now.astimezone(ZoneInfo(tz_name))
    session = "morning" if local.hour < 12 else "midday" if local.hour < 17 else "evening"
    return f"{local.date().isoformat()}-{session}", session, local


def _quiz(items):
    quiz = []
    for item in items[:6]:
        correct = TOPICS.index(item["topic"])
        quiz.append({
            "id": _id("q", item["id"]), "topic": item["topic"], "concept": item["concept_term"],
            "q": f"Which lens best fits this sourced update: “{item['title']}”?",
            "options": list(TOPICS), "answer_index": correct,
            "explanation": f"The update is grouped under {item['topic']}. Its practical concept is {item['concept_term'].lower()}.",
        })
    return quiz


def build_digest(now=None, previous=None, learner=None, fetcher=fetch_feed, tz_name="America/Los_Angeles",
                 market_fetcher=None, sentiment_fetcher=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    learner = learner or {"topics": []}
    interests = {row["topic"]: float(row.get("interest", .5)) for row in learner.get("topics", [])}
    failures, raw = [], []

    if market_fetcher is None:
        market_fetcher = fetch_market_snapshot if fetcher is fetch_feed else (lambda: [])
    try:
        market_snapshot = market_fetcher()
    except Exception as exc:
        market_snapshot = []
        failures.append({"source": "FRED market snapshot", "error": str(exc)[:120]})

    previous_sentiment = (previous or {}).get("sentiment") if isinstance((previous or {}).get("sentiment"), dict) else None
    reusable_sentiment = bool(
        previous_sentiment
        and previous_sentiment.get("status") in ("available", "stale")
        and previous_sentiment.get("themes")
    )
    sentiment = None
    if reusable_sentiment and previous_sentiment.get("as_of"):
        try:
            sentiment_age = now - datetime.fromisoformat(previous_sentiment["as_of"]).astimezone(timezone.utc)
            if sentiment_age < timedelta(hours=6):
                sentiment = dict(previous_sentiment)
                sentiment["cached"] = True
        except (TypeError, ValueError):
            pass
    if sentiment is None:
        if sentiment_fetcher is None:
            sentiment_fetcher = fetch_reddit_sentiment if fetcher is fetch_feed else (lambda: {})
        try:
            sentiment = sentiment_fetcher()
        except Exception as exc:
            failures.append({"source": "Reddit sentiment", "error": str(exc)[:120]})
            if reusable_sentiment:
                sentiment = dict(previous_sentiment)
                sentiment["cached"] = True
                sentiment["status"] = "stale"
            else:
                sentiment = {
                    "status": "unavailable", "label": "Community pulse unavailable", "score": 0,
                    "as_of": now.isoformat(), "post_count": 0, "confidence": "low", "themes": [],
                    "communities": [{"name": name, "posts": 0, "url": f"https://www.reddit.com/{name}/"}
                                    for name in REDDIT_COMMUNITIES.values()],
                    "method": "Reddit RSS could not be refreshed without exceeding its public rate limit.",
                    "caveat": "Open the linked communities directly; do not infer sentiment from missing data.",
                    "cached": False,
                }

    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(fetcher, source): source for source in SOURCES}
        for job in as_completed(jobs):
            source = jobs[job]
            try:
                raw.extend(parse_feed(job.result(), source, now))
            except Exception as exc:
                failures.append({"source": source.name, "error": str(exc)[:120]})

    cutoff = now - timedelta(days=8)
    unique = {}
    for row in raw:
        if row["published"] < cutoff or row["published"] > now + timedelta(days=1) or not _is_relevant(row):
            continue
        key = re.sub(r"[^a-z0-9]", "", row["title"].lower())[:180]
        if key and key not in unique:
            row["topic"] = _topic(row)
            row["theme"] = _theme(row)
            unique[key] = row
    ranked = sorted(unique.values(), key=lambda row: _rank(row, now, interests), reverse=True)

    # Keep a balanced radar: at least two from each topic when feeds permit.
    selected = []
    for topic in TOPICS:
        selected.extend([row for row in ranked if row["topic"] == topic][:3])
    selected_ids = {row["url"] for row in selected}
    selected.extend(row for row in ranked if row["url"] not in selected_ids)
    selected = selected[:12]
    selected.sort(key=lambda row: _decision_rank(row, now, interests), reverse=True)
    if not selected:
        raise RuntimeError("No recent items were available from the configured public feeds")

    previous_urls = {src["url"] for item in (previous or {}).get("items", []) for src in item.get("sources", [])}
    items = []
    for row in selected:
        term, definition = _concept(row)
        items.append({
            "id": _id("story", row["url"]), "topic": row["topic"], "title": row["title"],
            "summary": _sentence_summary(row), "why_it_matters": _why_it_matters(row["topic"]),
            "concept": f"{term}: {definition}", "concept_term": term, "theme": row["theme"],
            "published_at": row["published"].isoformat(), "source_name": row["source"],
            "source_kind": row.get("source_kind", "news"),
            "watch_next": _watch_next(row.get("source_kind", "news")),
            "is_new": row["url"] not in previous_urls,
            "sources": [{"title": row["source"], "url": row["url"]}],
        })

    market_words = ("stock", "shares", "market", "earnings", "investor", "bond", "yield", "bitcoin", "oil")
    mover_rows = [item for item in items if any(word in item["title"].lower() for word in market_words)]
    if len(mover_rows) < 3:
        mover_rows.extend(item for item in items if item["topic"] == "Markets & investing" and item not in mover_rows)
    movers = [{
        "id": _id("mover", item["id"]), "topic": "Markets & investing", "name": item["title"],
        "kind": "Sourced market signal", "what_happened": item["summary"],
        "takeaway": "Verify the source detail and the size of the reaction before treating this as a durable change.",
        "sources": item["sources"],
    } for item in mover_rows[:4]]

    theme_groups = {}
    for item in items:
        theme_groups.setdefault(item["theme"], []).append(item)
    trends = []
    for name, group in sorted(theme_groups.items(), key=lambda pair: len(pair[1]), reverse=True):
        if len(group) < 2:
            continue
        trends.append({
            "id": _id("trend", name), "topic": "Markets & investing", "trend": name,
            "evidence": "Appears across: " + "; ".join(item["title"] for item in group[:3]),
            "confidence": "medium" if len(group) == 2 else "high",
            "caveat": "Headline clustering is a signal to investigate, not proof of a lasting economic trend.",
        })
        if len(trends) == 3:
            break

    concepts = []
    seen_concepts = set()
    for item in items:
        term, definition = item["concept_term"], item["concept"].split(": ", 1)[-1]
        if term in seen_concepts:
            continue
        seen_concepts.add(term)
        concepts.append({
            "id": _id("concept", term), "topic": item["topic"], "term": term,
            "definition": definition, "example": f"Use it to examine “{item['title']}”.",
        })
        if len(concepts) == 6:
            break

    edition_id, session, local = _edition(now, tz_name)
    new_items = [item for item in items if item["is_new"]]
    source_names = sorted({item["source_name"] for item in items})
    period_start = (local.date() - timedelta(days=7)).isoformat()
    period_end = local.date().isoformat()

    def desk_items(kinds, limit=4):
        return [{"title": item["title"], "source": item["source_name"],
                 "published_at": item["published_at"], "url": item["sources"][0]["url"]}
                for item in items if item.get("source_kind") in kinds][:limit]

    manager_desk = {
        "mandate": "Find what changed in price drivers, expectations, estimates or risk—and identify the next fact that could disprove the view.",
        "sections": [
            {"title": "Macro & policy", "cadence": "Before the open", "question": "Did the expected path for growth, inflation, rates or liquidity change?", "items": desk_items(("macro", "policy"))},
            {"title": "Filings & ownership", "cadence": "Open, midday and after close", "question": "Did a filing alter earnings power, capital allocation, governance or ownership?", "items": desk_items(("filing",))},
            {"title": "Company & industry catalysts", "cadence": "Continuously", "question": "Which earnings, guidance, deals, regulation or supply-chain facts change estimates?", "items": desk_items(("news", "tech"))},
        ],
        "market_snapshot": market_snapshot,
        "reference_board": list(REFERENCE_BOARD),
        "daily_loop": [
            "Before the open: scan overnight cross-asset moves, today’s macro calendar, company catalysts and new filings.",
            "Midday: check unusual price/volume and relative moves, then look for the filing or news that explains them.",
            "After the close: read earnings and filings, record what changed in each thesis, review risk, and set tomorrow’s watch list.",
        ],
        "blind_spots": [
            "No live prices, portfolio positions, P&L, factor exposure or risk limits are connected yet.",
            "No Bloomberg/Refinitiv feed, broker research, expert-network calls, transcript license, order flow or proprietary alternative data.",
            "Public positioning is delayed: CFTC data is periodic, and Form 13F holdings can arrive up to 45 days after quarter-end.",
        ],
    }
    return {
        "edition_id": edition_id,
        "headline": f"Your {session} financial radar",
        "tldr": [f"{item['title']} — {item['source_name']}" for item in items[:4]],
        "movers": movers, "items": items, "trends": trends, "concepts": concepts,
        "decision_lens": [
            {"id": "lens-facts", "topic": "Markets & investing", "knowledge_point": "Separate the verified fact from the market narrative.", "questions_to_ask": ["What did the primary source actually say?", "What changed since the prior release?", "Is the reaction large relative to normal variation?"]},
            {"id": "lens-exposure", "topic": "Real estate & mortgages", "knowledge_point": "Translate news into your existing exposures—not a trade recommendation.", "questions_to_ask": ["Does this affect a rate, renewal, payment or deadline I already have?", "What would change my cash-flow assumptions?", "Which decision can safely wait for better evidence?"]},
            {"id": "lens-economics", "topic": "Tech, AI & industry", "knowledge_point": "Test adoption claims against durable economics.", "questions_to_ask": ["Who pays, and how repeatable is the demand?", "What are the variable and capital costs?", "What evidence would disprove the strongest claim?"]},
        ],
        "quiz": _quiz(items), "manager_desk": manager_desk, "sentiment": sentiment,
        "changes": [{"title": item["title"], "topic": item["topic"], "source": item["source_name"]} for item in new_items[:6]],
        "checklist": [
            "Open the primary source for the one takeaway most relevant to your existing exposure.",
            "Write one sentence: what changed, what did not, and what would overturn your view.",
            "Name the next catalyst or data release—and when it is expected.",
            "Do not make a buy, sell or timing decision from one briefing; use it to prepare better questions.",
        ],
        "daily_meta": {
            "generated_at": now.isoformat(), "period_start": period_start, "period_end": period_end,
            "session": session, "source_count": len(source_names), "sources": source_names,
            "story_count": len(items), "new_count": len(new_items), "failed_sources": failures,
            "method": "Free primary/public RSS and Atom aggregation with deterministic classification; no paid AI.",
        },
    }


def free_tutor_reply(item, question):
    topic = item.get("topic", "Markets & investing")
    concept = item.get("concept") or item.get("knowledge_point") or "Evidence quality"
    source = (item.get("sources") or [{}])[0]
    source_line = f"\n\nSource: [{source.get('title', 'Original source')}]({source.get('url')})" if source.get("url") else ""
    return (
        f"**What we know:** {item.get('summary') or item.get('what_happened') or item.get('definition') or item.get('title', '')}\n\n"
        f"**Concept:** {concept}\n\n"
        f"**How to use it:** For {topic.lower()}, separate the sourced fact from assumptions about what happens next. "
        f"A concrete example is to write down the next official data release or company disclosure that could confirm or weaken the claim."
        f"{source_line}\n\n→ What evidence would change this interpretation?\n→ Explain the concept more simply"
    )
