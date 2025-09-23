#!/usr/bin/env python3
"""
Daily Article Researcher Script

This script fetches articles from RSS feeds, extracts content, performs research using
Google Custom Search, and generates markdown files with the results.

Environment Variables:
    DOTENV_PATH: Path to .env file (default: .env)
    FEEDS_FILE: Path to feeds configuration file (default: feeds.json)
    HISTORY_FILE: Path to processed articles history (default: history.json)
    OUTPUT_DIR: Directory for generated articles (default: articles)
    RESULTS_PER_QUERY: Number of research results per query (default: 8)
    USER_AGENT: HTTP User Agent string
    DEFAULT_RSS: Default RSS feed URL
    GCS_API_KEY: Google Custom Search API key
    GCS_CX: Google Custom Search engine ID
"""

import os
import sys
import json
import csv
import re
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Optional, Any

import requests
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('fetch_articles.log') if os.getenv('LOG_TO_FILE') else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)


def getenv(key: str, default: Any = None) -> Any:
    """Get environment variable with optional default."""
    value = os.getenv(key, default)
    return value if value is not None else default


def load_environment():
    """Load environment variables from .env file if available."""
    try:
        from dotenv import load_dotenv
        dotenv_path = getenv("DOTENV_PATH", ".env")
        if Path(dotenv_path).is_file():
            load_dotenv(dotenv_path)
            logger.info(f"Loaded environment from {dotenv_path}")
    except ImportError:
        logger.warning("python-dotenv not available, skipping .env file loading")
    except Exception as e:
        logger.warning(f"Failed to load .env file: {e}")


class ArticleFetcher:
    """Main class for fetching and processing articles."""
    
    def __init__(self):
        """Initialize the ArticleFetcher with configuration."""
        load_environment()
        
        # Configuration
        self.feeds_file = getenv("FEEDS_FILE", "feeds.json")
        self.history_file = getenv("HISTORY_FILE", "history.json")
        self.output_dir = getenv("OUTPUT_DIR", "articles")
        self.results_per_query = int(getenv("RESULTS_PER_QUERY", "8"))
        self.user_agent = getenv("USER_AGENT", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
        self.default_rss = getenv("DEFAULT_RSS", "https://www.firearmsnews.com/RSS.aspx?websiteid=77508&listingid=77589")
        
        # API credentials
        self.gcs_api_key = getenv("GCS_API_KEY", "")
        self.gcs_cx = getenv("GCS_CX", "")
        
        # HTTP session setup
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })
        
        # Retry configuration
        self.max_retries = 3
        self.retry_delay = 5
        
        logger.info("ArticleFetcher initialized")

    def read_feeds(self, path: Path) -> List[Dict[str, Any]]:
        """Read feeds configuration from JSON or CSV file."""
        try:
            if not path.exists():
                logger.info(f"Feeds file {path} not found, creating default")
                data = [{"FeedURL": self.default_rss, "Active": True}]
                path.write_text(json.dumps(data, indent=2))
                return data
            
            if path.suffix.lower() == ".json":
                return json.loads(path.read_text())
            
            # CSV format
            feeds = []
            with path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    url = (row.get("FeedURL") or "").strip()
                    active = (row.get("Active") or "true").strip().lower() in ("1", "true", "yes", "y")
                    if url:
                        feeds.append({"FeedURL": url, "Active": active})
            return feeds
            
        except Exception as e:
            logger.error(f"Failed to read feeds from {path}: {e}")
            return [{"FeedURL": self.default_rss, "Active": True}]

    def read_history(self, path: Path) -> Set[str]:
        """Read processing history from JSON or CSV file."""
        try:
            if not path.exists():
                return set()
            
            if path.suffix.lower() == ".json":
                return set(json.loads(path.read_text()))
            
            # CSV format
            links = set()
            with path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    link = (row.get("Link") or "").strip()
                    if link:
                        links.add(link)
            return links
            
        except Exception as e:
            logger.error(f"Failed to read history from {path}: {e}")
            return set()

    def write_history(self, path: Path, links: Set[str]):
        """Write processing history to JSON or CSV file."""
        try:
            if path.suffix.lower() == ".json":
                path.write_text(json.dumps(sorted(links), indent=2))
            else:
                with path.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Link"])
                    for link in sorted(links):
                        writer.writerow([link])
            logger.info(f"Updated history file with {len(links)} entries")
        except Exception as e:
            logger.error(f"Failed to write history to {path}: {e}")

    def fetch_rss_first_item(self, url: str) -> Optional[Dict[str, str]]:
        """Fetch the first item from an RSS feed."""
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Fetching RSS from {url} (attempt {attempt + 1})")
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                
                root = ET.fromstring(response.content)
                item = root.find(".//item")
                
                if item is None:
                    logger.warning(f"No items found in RSS feed: {url}")
                    return None
                
                def get_text(tag: str) -> str:
                    element = item.find(tag)
                    return element.text.strip() if element is not None and element.text else ""
                
                result = {
                    "title": get_text("title"),
                    "link": get_text("link"),
                    "pubDate": get_text("pubDate"),
                    "description": get_text("description")
                }
                
                logger.info(f"Fetched article: {result['title']}")
                return result
                
            except Exception as e:
                if attempt == self.max_retries - 1:
                    logger.error(f"Failed to fetch RSS from {url} after {self.max_retries} attempts: {e}")
                    return None
                logger.warning(f"RSS fetch attempt {attempt + 1} failed: {e}, retrying in {self.retry_delay}s")
                time.sleep(self.retry_delay)

    def google_search(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Perform Google Custom Search."""
        if not (self.gcs_api_key and self.gcs_cx):
            logger.warning("Google Custom Search not configured")
            return []
        
        try:
            logger.debug(f"Performing Google search for: {query}")
            response = self.session.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": self.gcs_api_key,
                    "cx": self.gcs_cx,
                    "q": query,
                    "num": min(num_results, 10)
                },
                timeout=30
            )
            response.raise_for_status()
            
            items = response.json().get("items", [])
            results = []
            for item in items:
                results.append({
                    "title": item.get("title", "").strip(),
                    "link": item.get("link", "").strip(),
                    "snippet": (item.get("snippet") or "").strip()
                })
            
            logger.info(f"Found {len(results)} search results")
            return results
            
        except Exception as e:
            logger.error(f"Google Custom Search failed: {e}")
            return []

    def sanitize_filename(self, text: str) -> str:
        """Sanitize text for use as filename."""
        # Remove non-alphanumeric characters except spaces and hyphens
        text = re.sub(r"[^\w\s-]", "", text)
        # Replace multiple spaces/hyphens with single hyphen
        text = re.sub(r"[-\s]+", "-", text).strip("-").lower()
        return text or "article"

    def parse_rfc2822_date(self, date_string: str) -> datetime:
        """Parse RFC2822 date string."""
        try:
            return datetime.strptime(date_string, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        except Exception:
            logger.warning(f"Failed to parse date: {date_string}")
            return datetime.now(timezone.utc)

    def scrape_article_content(self, url: str) -> str:
        """Scrape article content from URL."""
        try:
            logger.debug(f"Scraping content from {url}")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, "html.parser")
            
            # Try multiple selectors to find content
            content_selectors = [
                "article",
                ".article-content",
                ".content",
                ".post-content",
                ".entry-content",
                "#content",
                ".main-content"
            ]
            
            content_root = None
            for selector in content_selectors:
                content_root = soup.select_one(selector)
                if content_root:
                    break
            
            if not content_root:
                # Fallback: use all paragraphs if there are enough
                paragraphs = soup.find_all("p")
                if len(paragraphs) >= 3:
                    content_root = soup
            
            if not content_root:
                logger.warning(f"No content found for {url}")
                return ""
            
            # Remove unwanted elements
            for element in content_root.find_all(["script", "style", "nav", "header", "footer", "aside"]):
                element.decompose()
            
            # Extract and clean text
            text = content_root.get_text("\n")
            text = re.sub(r"\n\s*\n", "\n\n", text)  # Remove excessive newlines
            text = re.sub(r"[ \t]+", " ", text)  # Normalize whitespace
            
            logger.info(f"Scraped {len(text)} characters from {url}")
            return text.strip()
            
        except Exception as e:
            logger.error(f"Failed to scrape content from {url}: {e}")
            return ""

    def write_markdown_file(self, article: Dict[str, str], search_results: List[Dict[str, str]], 
                          content: str, output_dir: Path) -> str:
        """Write article data to markdown file."""
        try:
            # Parse publication date
            pub_date = self.parse_rfc2822_date(article.get("pubDate", ""))
            date_slug = pub_date.strftime("%Y-%m-%d")
            display_date = pub_date.strftime("%B %d, %Y")
            
            # Get article details
            title = article.get("title") or "Untitled"
            link = article.get("link") or ""
            
            # Generate filename
            filename = f"{date_slug}-{self.sanitize_filename(title)}.md"
            filepath = output_dir / filename
            
            # Build markdown content
            lines = [
                f"# {title}\n",
                f"**Published:** {display_date}  ",
                f"**Original Link:** [{title}]({link})\n",
                "---\n"
            ]
            
            if content:
                lines.extend([
                    "## Article Text (extracted)\n",
                    content + "\n",
                    "---\n"
                ])
            
            lines.append("## Research Results\n")
            
            if search_results:
                for i, result in enumerate(search_results, 1):
                    result_title = result["title"].replace("\n", " ").strip()
                    result_url = result["link"].strip()
                    result_snippet = result["snippet"].replace("\n", " ").strip()
                    lines.append(f"{i}. **[{result_title}]({result_url})** — {result_snippet}")
                lines.append("")
            else:
                lines.append("_Google Custom Search not configured or no results._\n")
            
            lines.extend([
                "---\n",
                f"*Fetched on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}*"
            ])
            
            # Ensure output directory exists
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file
            filepath.write_text("\n".join(lines), encoding="utf-8")
            logger.info(f"Created article file: {filename}")
            
            return filename
            
        except Exception as e:
            logger.error(f"Failed to write markdown file: {e}")
            return ""

    def process_feeds(self) -> Dict[str, Any]:
        """Process all active feeds and return results."""
        root = Path(".").resolve()
        feeds_path = root / self.feeds_file
        history_path = root / self.history_file
        output_dir = root / self.output_dir
        
        logger.info(f"Processing feeds from {feeds_path}")
        
        # Load configuration
        feeds = self.read_feeds(feeds_path)
        history = self.read_history(history_path)
        
        processed_articles = []
        created_files = []
        
        for feed_config in feeds:
            if not feed_config.get("Active", True):
                continue
            
            rss_url = (feed_config.get("FeedURL") or "").strip()
            if not rss_url:
                continue
            
            # Fetch latest article from RSS
            article = self.fetch_rss_first_item(rss_url)
            if not article or not article.get("link"):
                continue
            
            article_link = article["link"].strip()
            if article_link in history:
                logger.info(f"Article already processed: {article.get('title', 'Unknown')}")
                continue
            
            title = (article.get("title") or "").strip()
            logger.info(f"Processing new article: {title}")
            
            # Perform research
            search_results = self.google_search(title, self.results_per_query)
            
            # Scrape article content
            content = self.scrape_article_content(article_link)
            
            # Write markdown file
            filename = self.write_markdown_file(article, search_results, content, output_dir)
            
            if filename:
                # Update history
                history.add(article_link)
                created_files.append(str((output_dir / filename).as_posix()))
                processed_articles.append({
                    "title": title,
                    "link": article_link,
                    "file": filename
                })
        
        # Save updated history
        self.write_history(history_path, history)
        
        return {
            "processed_articles": processed_articles,
            "created_files": created_files,
            "any_new": len(created_files) > 0
        }

    def generate_summary(self, results: Dict[str, Any]) -> str:
        """Generate workflow summary."""
        processed = results["processed_articles"]
        
        summary_lines = [
            "### Daily Article Researcher — Summary",
            f"- Feeds file: `{self.feeds_file}`",
            f"- History file: `{self.history_file}`",
            f"- Output dir: `{self.output_dir}`",
            ""
        ]
        
        if processed:
            summary_lines.append(f"**New articles:** {len(processed)}")
            for article in processed:
                summary_lines.append(f"- [{article['title']}]({article['link']}) → `articles/{article['file']}`")
        else:
            summary_lines.append("**New articles:** 0")
        
        summary_lines.extend([
            "",
            f"_Run at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}_"
        ])
        
        return "\n".join(summary_lines)


def main():
    """Main entry point."""
    try:
        fetcher = ArticleFetcher()
        results = fetcher.process_feeds()
        
        # Generate GitHub Actions outputs
        any_new = "true" if results["any_new"] else "false"
        
        # Write to GitHub Actions output file if available
        github_output = os.getenv("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"any_new={any_new}\n")
                f.write(f"new_files={json.dumps(results['created_files'])}\n")
        
        # Write to GitHub Actions step summary if available
        github_step_summary = os.getenv("GITHUB_STEP_SUMMARY")
        if github_step_summary:
            summary = fetcher.generate_summary(results)
            with open(github_step_summary, "a", encoding="utf-8") as f:
                f.write(summary + "\n")
        
        # Print notifications
        if results["processed_articles"]:
            print("::notice title=Daily Article Researcher::New article(s) added. See Job Summary for details.")
            logger.info(f"Successfully processed {len(results['processed_articles'])} new articles")
        else:
            print("::notice title=Daily Article Researcher::No new articles today. See Job Summary for details.")
            logger.info("No new articles found")
        
    except Exception as e:
        logger.error(f"Script failed: {e}")
        print(f"::error title=Daily Article Researcher::Script failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()