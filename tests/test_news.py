from datetime import datetime, timezone

from news import FeedSource, build_digest, fetch_reddit_sentiment, parse_feed


NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)


def rss(title="Mortgage rates shift as housing affordability changes", link="https://example.test/story"):
    return f"""<?xml version="1.0"?>
    <rss><channel><item><title>{title}</title><link>{link}</link>
    <description>Official data adds context for household costs and financial decisions.</description>
    <pubDate>Mon, 02 Nov 2026 16:00:00 GMT</pubDate></item></channel></rss>""".encode()


def reddit_atom():
    entries = [
        ("NVDA earnings and AI chip demand look strong", "investing", "17:00:00"),
        ("Are rate cuts back after the jobs report?", "stocks", "16:00:00"),
        ("Buying calls before semiconductor earnings", "wallstreetbets", "15:00:00"),
        ("Valuation and cash flow analysis for a large bank", "SecurityAnalysis", "14:00:00"),
        ("Is the market overvalued and vulnerable to a crash?", "investing", "13:00:00"),
    ]
    body = "".join(
        f"<entry><title>{title}</title><link href='https://www.reddit.com/r/{sub}/comments/example/post/'/>"
        f"<updated>2026-11-02T{clock}Z</updated><content>Discussion</content></entry>"
        for title, sub, clock in entries
    )
    return f"<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>{body}</feed>".encode()


def indexed_reddit_rss():
    items = [
        "AI chip earnings beat expectations - Reddit",
        "Are rate cuts back after the jobs report? - Reddit",
        "Apple revenue and valuation discussion - Reddit",
        "Oil prices may drive the market downturn - Reddit",
    ]
    body = "".join(
        f"<item><title>{title}</title><link>https://news.google.com/rss/articles/{i}</link>"
        f"<pubDate>Mon, 02 Nov 2026 16:00:0{i} GMT</pubDate></item>"
        for i, title in enumerate(items)
    )
    return f"<?xml version='1.0'?><rss><channel>{body}</channel></rss>".encode()


def test_parses_rss_and_preserves_source():
    source = FeedSource("Example", "https://example.test/feed", "Real estate & mortgages", True)
    rows = parse_feed(rss(), source, NOW)
    assert rows[0]["title"].startswith("Mortgage rates")
    assert rows[0]["url"] == "https://example.test/story"
    assert rows[0]["source"] == "Example"
    assert rows[0]["official"] is True


def test_builds_balanced_free_daily_digest():
    titles = {
        "Federal Reserve": "Federal Reserve publishes interest rate update",
        "SEC policy": "SEC announces new disclosure rule for investment funds",
        "SEC 8-K filings": "Company files 8-K with earnings guidance update",
        "SEC insider filings": "Executive reports company shares on Form 4",
        "BLS employment": "Employment and wages changed in the latest jobs report",
        "BLS inflation": "Consumer price inflation data released",
        "BEA economics": "GDP and consumer spending economic data released",
        "U.S. Treasury": "Treasury updates market financing estimates",
        "EIA energy": "Oil and gas market data update",
        "CFPB": "Mortgage servicing and home affordability update",
        "BBC Business": "Global stock markets respond to company earnings",
        "NPR Business": "Housing costs and rents shape household budgets",
        "BBC Technology": "Artificial intelligence companies increase chip spending",
        "Ars Technica": "Cloud software economics shift with new AI products",
    }

    def fetcher(source):
        slug = source.name.lower().replace(" ", "-")
        return rss(titles[source.name], f"https://example.test/{slug}")

    digest = build_digest(now=NOW, fetcher=fetcher)
    topics = {item["topic"] for item in digest["items"]}
    assert topics == {"Markets & investing", "Real estate & mortgages", "Tech, AI & industry"}
    assert digest["edition_id"] == "2026-11-02-morning"
    assert digest["daily_meta"]["source_count"] >= 9
    assert digest["daily_meta"]["story_count"] == 12
    assert digest["daily_meta"]["new_count"] == 12
    assert len(digest["quiz"]) == 6
    assert all(item["sources"][0]["url"].startswith("https://") for item in digest["items"])
    assert all(item["id"].startswith("story-") for item in digest["items"])
    assert digest["checklist"]
    assert digest["manager_desk"]["reference_board"]
    assert any(section["title"] == "Filings & ownership" for section in digest["manager_desk"]["sections"])


def test_detects_changes_from_previous_edition():
    def fetcher(source):
        slug = source.name.lower().replace(" ", "-")
        return rss(f"{source.name} financial update", f"https://example.test/{slug}")

    first = build_digest(now=NOW, fetcher=fetcher)
    second = build_digest(now=NOW, previous=first, fetcher=fetcher)
    assert second["daily_meta"]["new_count"] == 0
    assert second["changes"] == []


def test_builds_caveated_reddit_sentiment_from_titles_only():
    pulse = fetch_reddit_sentiment(data=reddit_atom(), now=NOW)
    assert pulse["status"] == "available"
    assert pulse["post_count"] == 5
    assert len(pulse["themes"]) == 3
    assert any(row["name"] == "r/wallstreetbets" for row in pulse["communities"])
    assert "attention, not evidence" in pulse["themes"][0]["takeaway"]
    assert "No comments" in pulse["method"]


def test_does_not_cache_an_unavailable_sentiment_result():
    calls = []
    previous = {
        "items": [],
        "sentiment": {
            "status": "unavailable", "as_of": NOW.isoformat(), "themes": [],
        },
    }

    def sentiment_fetcher():
        calls.append(True)
        return fetch_reddit_sentiment(data=reddit_atom(), now=NOW)

    digest = build_digest(
        now=NOW, previous=previous, fetcher=lambda _: rss(),
        sentiment_fetcher=sentiment_fetcher,
    )
    assert calls == [True]
    assert digest["sentiment"]["status"] == "available"


def test_builds_low_confidence_pulse_from_public_index_fallback():
    pulse = fetch_reddit_sentiment(data=indexed_reddit_rss(), now=NOW, indexed=True)
    assert pulse["status"] == "available"
    assert pulse["confidence"] == "low"
    assert pulse["post_count"] == 4
    assert all(not post["title"].endswith("- Reddit")
               for theme in pulse["themes"] for post in theme["posts"])
    assert "public news RSS index" in pulse["method"]
