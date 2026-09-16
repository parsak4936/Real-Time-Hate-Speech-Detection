"""
Trustpilot Review Adapter — brand-review comment ingestion.

Pulls consumer reviews for a brand's Trustpilot page and forwards each one
to Kafka under the SAME Universal Schema the YouTube / Twitch / Reddit
adapters use, so Tier-1, Tier-2, memory, RAG, and multi-agent all work on
Trustpilot data with no downstream change.

How it gets the data:
    Trustpilot has no free public read API, so this adapter reads the public
    review page HTML and parses the embedded `__NEXT_DATA__` JSON blob that
    Trustpilot's (Next.js) site ships in every page. That blob carries the
    full list of reviews for the page, which is far more robust than scraping
    rendered HTML. If the structure ever changes, the JSON-LD `<script
    type="application/ld+json">` block is used as a fallback (it carries a
    smaller `review` array in schema.org format).

    This is a passive, read-only scrape of public pages. Respect Trustpilot's
    terms of service and keep request volume modest (the --sleep guard and a
    page cap are here for that reason).

Usage (via omni_ingest.py):
    Paste a URL like:
        https://www.trustpilot.com/review/www.amazon.com
        https://www.trustpilot.com/review/amazon.com
        trustpilot.com/review/nike.com
    or just the business domain:
        www.amazon.com

References:
    - Review page:  https://www.trustpilot.com/review/<business-domain>
    - Pagination:   ?page=N
"""

import gzip
import html as _html
import json
import re
import time
import urllib.request
import zlib

from kafka import KafkaProducer

from adapters.context_agent import resolve_environment

KAFKA_TOPIC = "universal_stream"
KAFKA_SERVER = "127.0.0.1:9093"

# Full browser header set — Trustpilot rejects bare/non-browser requests. Note:
# Trustpilot also runs a JS/anti-bot challenge, so even these headers may return
# 403. When that happens, use a Trustpilot reviews dataset (e.g. Kaggle) via
# scripts/ingest/ingest_reviews_csv.py instead of live scraping.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}
DEFAULT_MAX_PAGES = 10
PAGE_SLEEP_SECONDS = 1.5

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_LD_JSON_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>',
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def extract_business_domain(url_or_name: str) -> str:
    """
    Accepts 'trustpilot.com/review/amazon.com', a full https URL, or just the
    bare business domain 'www.amazon.com'. Returns the business domain segment
    Trustpilot uses in /review/<domain>.
    """
    s = str(url_or_name).strip()
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("www.trustpilot.com", "trustpilot.com")
    if "trustpilot.com/review/" in s:
        s = s.split("trustpilot.com/review/", 1)[1]
    s = s.strip("/").split("?")[0].split("/")[0]
    return s


def _review_url(domain: str, page: int) -> str:
    base = f"https://www.trustpilot.com/review/{domain}"
    return base if page <= 1 else f"{base}?page={page}"


# ---------------------------------------------------------------------------
# Page fetch + parse
# ---------------------------------------------------------------------------

def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    resp = urllib.request.urlopen(req, timeout=15)
    raw = resp.read()
    enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc == "gzip":
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        raw = zlib.decompress(raw)
    return raw.decode("utf-8", errors="ignore")


def _dig(obj, *keys, default=None):
    """Safely walk nested dicts; return default on any missing key/type."""
    cur = obj
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def _parse_next_data_reviews(html_text: str):
    """Yield (review_id, author, text, title) from the __NEXT_DATA__ blob."""
    m = _NEXT_DATA_RE.search(html_text)
    if not m:
        return
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return

    reviews = _dig(data, "props", "pageProps", "reviews", default=None)
    if not isinstance(reviews, list):
        return

    for r in reviews:
        if not isinstance(r, dict):
            continue
        review_id = str(r.get("id") or r.get("reviewId") or "")
        author = _dig(r, "consumer", "displayName", default="") or "Anonymous"
        text = (r.get("text") or "").strip()
        title = (r.get("title") or "").strip()
        yield review_id, author, text, title


def _parse_ld_json_reviews(html_text: str):
    """Fallback: schema.org Review objects from JSON-LD blocks."""
    for m in _LD_JSON_RE.finditer(html_text):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            reviews = block.get("review") if isinstance(block, dict) else None
            if not isinstance(reviews, list):
                continue
            for r in reviews:
                if not isinstance(r, dict):
                    continue
                author = _dig(r, "author", "name", default="") or "Anonymous"
                body = (r.get("reviewBody") or r.get("description") or "").strip()
                title = (r.get("name") or "").strip()
                yield "", author, body, title


def _business_name(html_text: str, domain: str) -> str:
    m = _NEXT_DATA_RE.search(html_text)
    if m:
        try:
            data = json.loads(m.group(1))
            name = _dig(data, "props", "pageProps", "businessUnit", "displayName")
            if name:
                return name
        except json.JSONDecodeError:
            pass
    m = re.search(r'<meta property="og:title" content="(.*?)"', html_text)
    if m:
        return _html.unescape(m.group(1).strip())
    return domain


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def start_trustpilot_pipeline(url_or_name: str, max_pages: int = DEFAULT_MAX_PAGES):
    domain = extract_business_domain(url_or_name)
    if not domain:
        print("[Trustpilot Adapter] Could not parse a business domain from input.")
        return

    print(f"-> [Trustpilot Adapter] Target business: {domain}")

    # Fetch page 1 for metadata + the Context Agent.
    try:
        first_html = _fetch_html(_review_url(domain, 1))
    except Exception as e:
        print(f"-> [Trustpilot Adapter] Could not fetch the review page: {e}")
        if "403" in str(e):
            print("-> Trustpilot is blocking automated requests (JS/anti-bot protection).")
            print("-> Live scraping won't work. Use a Trustpilot reviews dataset instead:")
            print("->   python scripts/ingest/ingest_reviews_csv.py <reviews.csv> --platform Trustpilot")
            print("-> (or wait for the supervisor's resource — see docs/MEETING_2026-06-18.md).")
        return

    business = _business_name(first_html, domain)
    raw_meta = {
        "business_domain": domain,
        "business_name": business,
        "title": f"Trustpilot reviews — {business}",
        "description": f"Consumer reviews for {business} ({domain}) on Trustpilot.",
        "is_live": True,
    }

    print("\n--- EXTRACTED TRUSTPILOT METADATA ---")
    print(f"Business: {business}")
    print(f"Domain:   {domain}")
    print("-------------------------------------")

    print("\n-> [Trustpilot Adapter] Requesting Context Resolution from XAI Agent...")
    env = resolve_environment("Trustpilot", raw_meta)
    domain_disp = env["env_domain"]
    subgenre = env["env_subgenre"]
    subgenre_display = f"/{subgenre}" if subgenre else ""
    print(
        f"-> [Trustpilot Adapter] Context Locked: [{domain_disp.upper()}{subgenre_display}] | "
        f"Strictness: [{env['env_strictness'].upper()}] | Match: {env['env_domain_match']} | "
        f"LLM raw proposal: {env['env_domain_raw']!r}"
    )

    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_SERVER,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    except Exception as e:
        print(f"-> [Kafka Error] Could not connect to message bus: {e}")
        return

    print(f"\n----- TRUSTPILOT INGEST ACTIVE for {domain} -----")

    sent = 0
    seen_ids = set()
    try:
        for page in range(1, max_pages + 1):
            page_html = first_html if page == 1 else _fetch_html(_review_url(domain, page))

            reviews = list(_parse_next_data_reviews(page_html))
            if not reviews:
                reviews = list(_parse_ld_json_reviews(page_html))
            if not reviews:
                print(f"-> [Trustpilot Adapter] No reviews parsed on page {page}; stopping.")
                break

            page_new = 0
            for idx, (review_id, author, text, title) in enumerate(reviews):
                # Combine title + body — toxicity may live in either.
                content = (f"{title}. {text}" if title and text else (text or title)).strip()
                if not content:
                    continue

                rid = review_id or f"{domain}-p{page}-{idx}"
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                page_new += 1
                sent += 1

                message = {
                    "payload_text":             content,
                    "source_platform":          "Trustpilot",
                    "env_domain":               env["env_domain"],
                    "env_domain_raw":           env["env_domain_raw"],
                    "env_domain_match":         env["env_domain_match"],
                    "env_subgenre":             env["env_subgenre"],
                    "env_strictness":           env["env_strictness"],
                    "env_strictness_reasoning": env["env_strictness_reasoning"],
                    "platform_metadata": {
                        "video_id":     f"trustpilot-{domain}",      # thread id
                        "video_title":  business,
                        "channel_name": domain,
                        "tweet_id":     f"trustpilot-{rid}",         # message id
                        "author_id":    author,
                        "author_name":  author,
                        "is_moderator": False,
                        "is_sponsor":   False,
                    },
                }
                producer.send(KAFKA_TOPIC, message)
                print(f"[{domain_disp.upper()}{subgenre_display}] {author}: {content[:120]}")

            print(f"-> [Trustpilot Adapter] Page {page}: {page_new} new reviews.")
            if page < max_pages:
                time.sleep(PAGE_SLEEP_SECONDS)

    except KeyboardInterrupt:
        print("\n-> [Trustpilot Adapter] Ingest safely terminated.")
    except Exception as e:
        print(f"-> [Trustpilot Adapter] Ingest error: {e}")
    finally:
        # CRITICAL: flush the async Kafka buffer before exit, or short runs
        # lose pending messages (same guard as the other adapters).
        try:
            print("-> [Trustpilot Adapter] Flushing Kafka producer buffer...")
            producer.flush(timeout=10)
            producer.close(timeout=5)
            print(f"-> [Trustpilot Adapter] Producer closed. {sent} reviews sent this session.")
        except Exception as e:
            print(f"-> [Trustpilot Adapter] Producer flush failed: {e}")


if __name__ == "__main__":
    print("Run this adapter via omni_ingest.py, not directly.")
