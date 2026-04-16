# FreeGunner Refactoring Recommendations

**Report date:** 2026-03-19  
**Scope:** `scripts/fetch_articles.py`, `.github/workflows/get-articles-daily.yml`, `feeds.json`, `history.json`

---

## Executive Summary

The FreeGunner Daily Article Researcher is a functional Python application that fetches articles from RSS feeds, scrapes their content, and enriches them with Google Custom Search results before writing Markdown files. The core logic is sound, but several architectural choices impose unnecessary performance costs and reliability risks. This report details twelve concrete recommendations, ordered by impact, along with example code patterns for each.

---

## Recommendations

### 1. Process Feeds Concurrently (High Impact)

**Current behaviour:** `process_feeds()` iterates over feeds with a plain `for` loop, so every RSS fetch, article scrape, and Google search call blocks the next feed from starting.

**Problem:** With seven active feeds and three network calls per feed (RSS + scrape + search) at up to 30 s each, a single slow host can push total runtime close to the 30-minute job timeout.

**Recommendation:** Replace the sequential loop with `concurrent.futures.ThreadPoolExecutor`. Each feed's pipeline (fetch → scrape → search → write) can run in a separate worker thread, cutting wall-clock time to roughly the duration of the single slowest feed.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

MAX_WORKERS = 4  # respect rate limits; tune as needed

def _process_single_feed(self, feed_config, history):
    """Process one feed; return (article_meta, filename) or None."""
    ...

def process_feeds(self):
    feeds = self.read_feeds(feeds_path)
    history = self.read_history(history_path)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(self._process_single_feed, fc, history): fc
            for fc in feeds if fc.get("Active", True)
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                created_files.append(result)
```

---

### 2. Fetch All New RSS Items, Not Just the First (High Impact)

**Current behaviour:** `fetch_rss_first_item()` retrieves only the first `<item>` in each feed, so any feed that publishes more than one article per day silently drops the extra articles.

**Problem:** Multiple new articles go unprocessed every time a source posts more frequently than the cron interval.

**Recommendation:** Rename the method `fetch_rss_items()`, return a list of all items, and let `process_feeds()` filter out already-seen links using the history set.

```python
def fetch_rss_items(self, url: str) -> List[Dict[str, str]]:
    """Return ALL items from an RSS feed, newest first."""
    ...
    return [
        {"title": ..., "link": ..., "pubDate": ..., "description": ...}
        for item in root.findall(".//item")
    ]
```

---

### 3. Use a Requests Retry Adapter Instead of Hand-Rolled Retry Loops (Medium Impact)

**Current behaviour:** `fetch_rss_first_item()` wraps a `for attempt in range(self.max_retries)` loop with `time.sleep()`. The same retry pattern would need to be duplicated in `google_search()` and `scrape_article_content()` to be consistent.

**Problem:** Custom retry code is error-prone (sleep before first attempt on some code paths), inconsistent (only RSS retries, not search/scrape), and does not implement exponential back-off.

**Recommendation:** Attach a `urllib3`/`requests` `HTTPAdapter` with a `Retry` object to the shared session at initialisation time. All methods then benefit automatically.

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retry_strategy = Retry(
    total=3,
    backoff_factor=2,          # 2 s, 4 s, 8 s
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
self.session.mount("https://", adapter)
self.session.mount("http://", adapter)
```

---

### 4. Parse RFC 2822 Dates with the Standard Library (Medium Impact)

**Current behaviour:** `parse_rfc2822_date()` calls `datetime.strptime()` with a single hard-coded format string. Any deviation (e.g. a numeric timezone like `+0000` instead of `GMT`) raises an exception and falls back to "now", creating incorrect filenames.

**Problem:** RSS feeds are produced by dozens of different CMS platforms, each with slightly different date serialisation. Hard-coding one format causes silent data errors.

**Recommendation:** Use the `email.utils.parsedate_to_datetime()` function from the Python standard library, which implements the full RFC 2822 spec:

```python
from email.utils import parsedate_to_datetime

def parse_rfc2822_date(self, date_string: str) -> datetime:
    try:
        return parsedate_to_datetime(date_string)
    except Exception:
        logger.warning(f"Could not parse date '{date_string}', using current time")
        return datetime.now(timezone.utc)
```

---

### 5. Wire the `debug_mode` Workflow Input to the Script's Log Level (Medium Impact)

**Current behaviour:** The workflow defines a `debug_mode` boolean input and sets `DEBUG_MODE` in the environment, but `fetch_articles.py` never reads it. The script always logs at `INFO` level.

**Problem:** The debug toggle is a documented, user-facing feature that silently has no effect.

**Recommendation:** Read `DEBUG_MODE` at the top of `main()` and adjust the root logger accordingly:

```python
def main():
    if os.getenv("DEBUG_MODE", "false").lower() == "true":
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    ...
```

---

### 6. Use a More Robust Content Extractor (Medium Impact)

**Current behaviour:** `scrape_article_content()` tries a fixed list of CSS selectors, then falls back to collecting all `<p>` tags. Many modern news sites use dynamically generated class names or Shadow DOM components that none of the static selectors match.

**Problem:** The fallback silently returns an empty string for a significant fraction of articles, leaving the Markdown files with no extracted content.

**Recommendation:** Add `readability-lxml` (also known as `python-readability`) to `requirements.txt`. It uses a heuristic algorithm (derived from Mozilla Readability) that works reliably across diverse HTML structures:

```python
# requirements.txt addition:
# readability-lxml>=0.8.1

from readability import Document

def scrape_article_content(self, url: str) -> str:
    response = self.session.get(url, timeout=30)
    response.raise_for_status()
    doc = Document(response.text)
    soup = BeautifulSoup(doc.summary(), "html.parser")
    return soup.get_text("\n").strip()
```

---

### 7. Rate-Limit Google Custom Search Calls (Medium Impact)

**Current behaviour:** When multiple feeds produce new articles in the same run, `google_search()` is called for each in rapid succession with no delay between calls.

**Problem:** Google Custom Search has a default quota of 100 queries per day and enforces per-second rate limits. Bursting requests will generate `429` errors and waste quota that could be spread across future runs.

**Recommendation:** Add a configurable inter-request delay and enforce it between search calls:

```python
SEARCH_DELAY_SECONDS = float(os.getenv("SEARCH_DELAY", "1.0"))

# In process_feeds(), before calling google_search():
if search_calls_made > 0:
    time.sleep(SEARCH_DELAY_SECONDS)
search_calls_made += 1
results = self.google_search(title, self.results_per_query)
```

---

### 8. Replace the In-Memory History Set with SQLite for Scalability (Low–Medium Impact)

**Current behaviour:** `read_history()` loads the entire `history.json` file into a Python `set` in memory. `write_history()` re-serialises and overwrites the entire file after every run.

**Problem:** As the article archive grows (currently ~80 articles, but the project is young), the JSON file will grow proportionally. Loading and writing the entire file on every run is wasteful, and the JSON format does not support concurrent writers.

**Recommendation:** Migrate history storage to a local SQLite database. Lookups are O(log n) with an index, and inserts are atomic:

```python
import sqlite3

HISTORY_DB = os.getenv("HISTORY_DB", "history.db")

def _db_conn(self):
    conn = sqlite3.connect(HISTORY_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen (url TEXT PRIMARY KEY)"
    )
    return conn

def url_seen(self, url: str) -> bool:
    with self._db_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM seen WHERE url=?", (url,)
        ).fetchone() is not None

def mark_seen(self, url: str):
    with self._db_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen VALUES (?)", (url,)
        )
```

---

### 9. Normalise Article URLs Before History Lookup (Low Impact)

**Current behaviour:** URLs are stored and compared as raw strings. The same article accessed with and without a trailing slash, or with different query-string tracking parameters (e.g. `?utm_source=rss`), will be treated as distinct entries.

**Problem:** Duplicate Markdown files are created whenever a feed slightly varies its URL formatting.

**Recommendation:** Strip tracking parameters and normalise URLs before storing or comparing them:

```python
from urllib.parse import urlparse, urlencode, parse_qsl, urlunparse

def normalise_url(self, url: str) -> str:
    """Strip UTM and other tracking parameters."""
    TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"}
    parsed = urlparse(url)
    # parse_qsl returns (key, value) tuples, which urlencode accepts directly.
    clean_qs = [(k, v) for k, v in parse_qsl(parsed.query) if k not in TRACKING_PARAMS]
    return urlunparse(parsed._replace(query=urlencode(clean_qs), fragment=""))
```

---

### 10. Defer Logging Handler Setup to the Application Entry Point (Low Impact)

**Current behaviour:** The `logging.basicConfig()` call at module level conditionally creates a `FileHandler` based on the `LOG_TO_FILE` environment variable at *import time*, before `load_environment()` has a chance to set that variable from `.env`.

**Problem:** Log-to-file configuration via `.env` never takes effect because `.env` is loaded inside `ArticleFetcher.__init__()`, which runs after the module-level `basicConfig()` call.

**Recommendation:** Move logging configuration into a dedicated `setup_logging()` function called at the start of `main()`, after `load_environment()`:

```python
def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    handlers = [logging.StreamHandler(sys.stdout)]
    if os.getenv("LOG_TO_FILE"):
        handlers.append(logging.FileHandler("fetch_articles.log"))
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s",
                        handlers=handlers)

def main():
    load_environment()
    setup_logging(debug=os.getenv("DEBUG_MODE", "false").lower() == "true")
    ...
```

---

### 11. Add a `force_refresh` Code Path to the Script (Low Impact)

**Current behaviour:** The workflow exposes a `force_refresh` boolean input that sets a `FORCE_REFRESH` environment variable, but the Python script never reads it. History is always consulted, so the feature does nothing.

**Problem:** Another documented, user-facing feature that silently has no effect.

**Recommendation:** Read `FORCE_REFRESH` in `process_feeds()` and bypass the history check when it is set:

```python
force_refresh = os.getenv("FORCE_REFRESH", "false").lower() == "true"
if not force_refresh and article_link in history:
    logger.info(f"Skipping already-processed article: {title}")
    continue
```

---

### 12. Validate RSS Feed URLs at Start-up (Low Impact)

**Current behaviour:** Invalid or malformed URLs in `feeds.json` are not detected until `fetch_rss_first_item()` raises an exception at run time.

**Problem:** A typo in `feeds.json` wastes a full retry cycle (up to 15 s) before being reported as an error.

**Recommendation:** Validate all feed URLs immediately after loading `feeds.json`, before any network I/O:

```python
from urllib.parse import urlparse

def validate_feeds(self, feeds: List[Dict]) -> List[Dict]:
    valid = []
    for f in feeds:
        url = (f.get("FeedURL") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            valid.append(f)
        else:
            logger.warning(f"Skipping invalid feed URL: {url!r}")
    return valid
```

---

## Summary Table

| # | Recommendation | Impact | Effort |
|---|----------------|--------|--------|
| 1 | Concurrent feed processing (`ThreadPoolExecutor`) | High | Medium |
| 2 | Fetch all new RSS items, not just the first | High | Low |
| 3 | Requests retry adapter (replace hand-rolled retries) | Medium | Low |
| 4 | RFC 2822 date parsing via `email.utils` | Medium | Low |
| 5 | Wire `debug_mode` input to log level | Medium | Low |
| 6 | `readability-lxml` for content extraction | Medium | Medium |
| 7 | Rate-limit Google Custom Search calls | Medium | Low |
| 8 | SQLite history store (replace JSON flat file) | Low–Medium | Medium |
| 9 | URL normalisation before history lookup | Low | Low |
| 10 | Defer logging setup to entry point | Low | Low |
| 11 | Implement `force_refresh` in the script | Low | Low |
| 12 | Validate RSS feed URLs at start-up | Low | Low |

---

## Recommended Prioritisation

**Immediate wins (low effort, clear improvement):**
- Items 2, 3, 4, 5, 9, 10, 11, 12 — each requires fewer than 20 lines of code change.

**Short-term improvements:**
- Items 1 and 7 — concurrent processing with a rate-limited search queue will substantially reduce runtime and API quota burn.

**Longer-term refactoring:**
- Items 6 and 8 — adding `readability-lxml` and migrating to SQLite require dependency and schema changes but will pay dividends as the feed list and article history grow.
