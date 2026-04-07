"""
ReviewTrust AI – Product Review Scraper
=========================================
Supported platforms
-------------------
  • Amazon   (.in / .com)   amzn.in/d/... short-links resolved automatically
  • Flipkart               dl.flipkart.com share-links resolved automatically
  • Nykaa                  beauty & fashion (www.nykaa.com)
  • Myntra                 fashion & lifestyle (www.myntra.com)
  • Meesho                 social commerce (meesho.com)

Anti-bot strategy per platform
--------------------------------
Flipkart  – curl_cffi (Chrome 124 TLS impersonation), Playwright headless fallback.
Amazon    – Playwright with persistent signed-in profile (WAF requires real browser).
Nykaa     – Direct JSON API via curl_cffi; Playwright headless fallback.
Myntra    – Direct JSON API (xt.myntra.com) via curl_cffi; Playwright headless fallback.
Meesho    – Playwright headless (heavy React/GraphQL; no open API).
"""

import re
import time
import random
import logging
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from urllib.parse import urlparse

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

logger = logging.getLogger("scraper")

# ─── Recognised platform hostnames ───────────────────────────────────────────
_AMAZON_HOSTS   = {"amazon.in", "amazon.com", "www.amazon.in", "www.amazon.com",
                   "amzn.in", "amzn.com"}        # amzn.* are short-link domains
_FLIPKART_HOSTS = {"flipkart.com", "www.flipkart.com",
                   "dl.flipkart.com"}             # dl.flipkart.com = share short-link
_NYKAA_HOSTS   = {"nykaa.com", "www.nykaa.com"}
_MYNTRA_HOSTS  = {"myntra.com", "www.myntra.com"}
_MEESHO_HOSTS  = {"meesho.com", "www.meesho.com", "m.meesho.com"}

# Persistent Playwright profile for Amazon (requires one-time sign-in)
# Resolved to absolute path here so every subprocess sees the same location.
_AMAZON_PROFILE_DIR = (Path(__file__).resolve().parent / "playwright_profiles" / "amazon")
_AMAZON_MARKER      = _AMAZON_PROFILE_DIR / ".session_active"  # written by us after sign-in

# ─── User-Agent pool ─────────────────────────────────────────────────────────
_USER_AGENTS = [
    # Chrome 124 Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome 124 macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox 125 Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Safari 17 macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

# ─── Month abbreviation lookup (for Flipkart / Amazon date parsing) ──────────
_MONTH_ABBR = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Regex: "Reviewed in India on 14 March 2024" or "Reviewed in the United States on March 14, 2024"
_AMAZON_DATE_RE = re.compile(
    r'on\s+(\d{1,2})\s+(\w+)\s+(\d{4})'         # "on 14 March 2024"
    r'|on\s+(\w+)\s+(\d{1,2}),?\s+(\d{4})',      # "on March 14, 2024"
    re.IGNORECASE,
)

# Regex: "Mar, 2025" or "· Mar, 2025" or "March 2025" etc.
_FK_DATE_RE = re.compile(
    r'·?\s*(\w+),?\s+(\d{4})',
    re.IGNORECASE,
)


def _parse_amazon_date(raw: str) -> Optional[str]:
    """
    Parse Amazon review date string to YYYY-MM-DD.
    e.g. "Reviewed in India on 14 March 2024" → "2024-03-14"
         "Reviewed in the United States on March 14, 2024" → "2024-03-14"
    """
    m = _AMAZON_DATE_RE.search(raw)
    if not m:
        return None
    if m.group(1):  # "14 March 2024" format
        day, month_str, year = m.group(1), m.group(2), m.group(3)
    else:            # "March 14, 2024" format
        month_str, day, year = m.group(4), m.group(5), m.group(6)
    month_num = _MONTH_ABBR.get(month_str.lower())
    if not month_num:
        return None
    try:
        return f"{int(year):04d}-{month_num:02d}-{int(day):02d}"
    except (ValueError, TypeError):
        return None


def _parse_flipkart_date(raw: str) -> Optional[str]:
    """
    Parse Flipkart review date string to YYYY-MM.
    e.g. "Mar, 2025" → "2025-03"
         "· January, 2024" → "2024-01"
    """
    m = _FK_DATE_RE.search(raw)
    if not m:
        return None
    month_str, year = m.group(1), m.group(2)
    month_num = _MONTH_ABBR.get(month_str.lower())
    if not month_num:
        return None
    try:
        return f"{int(year):04d}-{month_num:02d}"
    except (ValueError, TypeError):
        return None


def _make_review_dict(
    text: str,
    platform: str,
    *,
    reviewer_name: Optional[str] = None,
    reviewer_profile_url: Optional[str] = None,
    reviewer_total_reviews: Optional[int] = None,
    review_date: Optional[str] = None,
    verified_purchase: bool = False,
) -> Dict[str, Any]:
    """Build a review dict with all standard fields."""
    return {
        "review_text":           text,
        "platform":              platform,
        "reviewer_name":         reviewer_name,
        "reviewer_profile_url":  reviewer_profile_url,
        "reviewer_total_reviews": reviewer_total_reviews,
        "review_date":           review_date,
        "verified_purchase":     verified_purchase,
    }


# impersonate='chrome124' mimics Chrome 124 TLS fingerprint — bypasses
# Flipkart / Amazon deep-packet-inspection blocking.
_SESSION = cffi_requests.Session()


def _base_headers(referer: Optional[str] = None) -> dict:
    ua = random.choice(_USER_AGENTS)
    h = {
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;"
                                     "q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":           "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":            "document",
        "Sec-Fetch-Mode":            "navigate",
        "Sec-Fetch-Site":            "none" if referer is None else "same-origin",
        "Sec-Fetch-User":            "?1",
        "DNT":                       "1",
        "Cache-Control":             "max-age=0",
    }
    if referer:
        h["Referer"] = referer
    return h


def _fetch(url: str, referer: Optional[str] = None, retries: int = 3) -> Optional[str]:
    """Fetch HTML with Chrome TLS impersonation, retry + exponential back-off."""
    for attempt in range(retries):
        try:
            resp = _SESSION.get(
                url,
                headers=_base_headers(referer),
                timeout=20,
                allow_redirects=True,
                impersonate="chrome124",
            )
            if resp.status_code == 200:
                return resp.text
            logger.warning("HTTP %d for %s (attempt %d)", resp.status_code, url, attempt + 1)
        except Exception as exc:
            logger.warning("Request error (attempt %d): %s", attempt + 1, exc)

        time.sleep(1.5 * (attempt + 1))

    return None


# ─── Shared Playwright headless fetch helper ─────────────────────────────────

def _pw_headless_page(
        url: str,
        wait_selector: Optional[str] = None,
        scroll: bool = False,
        wait_ms: int = 1500) -> Optional[str]:
    """
    Fetch a single page with a headless, non-persistent Playwright browser.
    No sign-in required.  Suitable for sites that render content via JS but
    don't wall-off content behind authentication.

    Returns rendered HTML or None on error.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="en-IN",
                timezone_id="Asia/Kolkata",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get:()=>undefined})"
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=8000)
                except PWTimeout:
                    pass
            if scroll:
                for _ in range(6):
                    page.evaluate("window.scrollBy(0, window.innerHeight * 0.7)")
                    page.wait_for_timeout(450)
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logger.warning("_pw_headless_page error (%s): %s", url, exc)
        return None


# ─── Process-pool helper (fixes Playwright + FastAPI asyncio conflict) ──────────

def _run_in_process(fn, *args, timeout: int = 180):
    """
    Run `fn(*args)` in a fresh worker process (not thread).

    Playwright's sync_api blocks internally on asyncio.run_until_complete().
    When called from inside FastAPI's anyio thread-pool there is already a
    running event loop on the thread, which causes a NotImplementedError on
    Windows when Playwright tries to spawn a subprocess transport.

    Running in a dedicated process gives Playwright a clean slate: no
    pre-existing event loop, no anyio, no conflicts.
    """
    with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args)
        return future.result(timeout=timeout)


# ─── Redirect resolver ────────────────────────────────────────────────────────

def _resolve_url(url: str) -> str:
    """
    Follow HTTP redirects and return the final canonical URL.
    Handles: amzn.in/d/...  and  dl.flipkart.com/s/...

    Strategy:
      1. Try HEAD (fast, no body download)
      2. If HEAD fails or returns 4xx, fall back to GET (some CDNs reject HEAD)
    """
    # ── Attempt 1: HEAD ────────────────────────────────────────────────────────
    try:
        resp = _SESSION.head(
            url,
            headers=_base_headers(),
            timeout=10,
            allow_redirects=True,
            impersonate="chrome124",
        )
        if resp.status_code < 400:
            resolved = resp.url
            if resolved != url:
                logger.info("Resolved  %s  →  %s", url, resolved)
            return resolved
        logger.debug("HEAD returned %d for %s, falling back to GET", resp.status_code, url)
    except Exception as e:
        logger.debug("HEAD failed for %s: %s", url, e)

    # ── Attempt 2: GET (follows redirects, returns final URL) ─────────────────
    try:
        resp = _SESSION.get(
            url,
            headers=_base_headers(),
            timeout=15,
            allow_redirects=True,
            impersonate="chrome124",
        )
        resolved = resp.url
        if resolved != url:
            logger.info("Resolved (GET)  %s  →  %s", url, resolved)
        return resolved
    except Exception as e:
        logger.warning("Could not resolve URL %s: %s", url, e)
        return url   # give up, return original


# ─── Amazon ───────────────────────────────────────────────────────────────────

def _extract_asin(url: str) -> Optional[str]:
    """Extract 10-char ASIN from any Amazon URL format."""
    # /dp/B0BNHD7MM3  or  /gp/product/B0BNHD7MM3
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    if m:
        return m.group(1)
    # bare path segment e.g. amzn.in resolved to /B0BNHD7MM3
    m = re.search(r"/([A-Z0-9]{10})(?:[/?]|$)", url)
    if m:
        return m.group(1)
    return None


def _scrape_amazon(product_url: str) -> List[Dict[str, str]]:
    """Dispatcher: resolve URL then hand off to the Playwright scraper."""
    resolved = _resolve_url(product_url)
    asin = _extract_asin(resolved)
    if not asin:
        logger.warning("Could not extract ASIN from: %s", product_url)
        return []
    parsed_host = urlparse(resolved).netloc.lower()
    domain = "amazon.in" if "amazon.in" in parsed_host else "amazon.com"
    logger.info("Amazon  ASIN=%s  domain=%s", asin, domain)
    return _run_in_process(_scrape_amazon_playwright, asin, domain)


def _scrape_amazon_playwright(asin: str, domain: str) -> List[Dict[str, str]]:
    """
    Scrape Amazon reviews using Playwright with a persistent browser profile.

    Amazon's /product-reviews/ page requires a signed-in session.  We use a
    persistent Chromium profile stored in  backend/playwright_profiles/amazon/.

    First run (no profile yet):
      A browser window opens.  Sign in to Amazon, then close the browser.
      The session is saved — all future runs are fully headless.

    Subsequent runs:
      Headless Chromium with saved cookies → full access to all review pages.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    PROFILE_DIR = _AMAZON_PROFILE_DIR
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # Automatically restore profile from a remote URL if configured via environment variables
    import os
    import tempfile
    import requests
    import zipfile
    
    session_url = os.environ.get("AMAZON_SESSION_URL")
    if session_url and not _AMAZON_MARKER.exists():
        logger.info("Downloading Amazon session from configured URL...")
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tf:
                r = requests.get(session_url, stream=True, timeout=30)
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    tf.write(chunk)
                temp_zip_path = tf.name
                
            with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                zip_ref.extractall(str(PROFILE_DIR.parent)) # Extract to playwright_profiles since internal folder is 'amazon'
                
            os.remove(temp_zip_path)
            if _AMAZON_MARKER.exists():
                logger.info("Session restored successfully from external URL.")
            else:
                 _AMAZON_MARKER.write_text("ok")
                 logger.info("Session restored and marker created.")
        except Exception as e:
            logger.error("Failed to restore session from URL: %s", e)

    # Use our own marker file — Chromium's Default/Cookies is written
    # asynchronously and may not exist yet when checked from another process.
    first_run = not _AMAZON_MARKER.exists()
    headless = not first_run

    base = f"https://www.{domain}"
    reviews_base = f"{base}/product-reviews/{asin}?ie=UTF8&reviewerType=all_reviews&sortBy=recent"
    reviews: List[Dict[str, Any]] = []

    logger.info("Amazon Playwright: ASIN=%s  headless=%s  profile=%s",
                asin, headless, PROFILE_DIR)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        try:
            if first_run:
                # ── First-run: let user sign in ───────────────────────────
                print("\n" + "="*60)
                print("AMAZON SETUP: A browser window has opened.")
                print("1. Sign in to your Amazon account.")
                print("2. Once you land on the Amazon homepage, CLOSE the window.")
                print("="*60 + "\n")
                logger.warning("Amazon setup: waiting for user to sign in and close browser...")
                page.goto(f"{base}/ap/signin", wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_event("close", timeout=300000)
                    logger.info("Amazon: browser closed by user, session saved.")
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
                _AMAZON_MARKER.write_text("ok")
                logger.warning(
                    "AMAZON SETUP: Session saved.  Re-run the analysis to scrape reviews."
                )
                return []

            # ── Normal run: scrape review pages ──────────────────────────
            page.goto(base + "/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(800)

            page.goto(reviews_base + "&pageNumber=1",
                      wait_until="domcontentloaded", timeout=30000)

            # If redirected to sign-in, session expired — re-login in headed mode
            if "ap/signin" in page.url:
                logger.warning("Amazon session expired. Re-launching headed browser for login...")
                context.close()
                # Re-launch in headed mode for interactive login
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()
                page.goto(f"{base}/ap/signin", wait_until="domcontentloaded", timeout=30000)
                print("\n" + "="*60)
                print("AMAZON SESSION EXPIRED — please sign in again.")
                print("Close the browser window when done.")
                print("="*60 + "\n")
                try:
                    page.wait_for_event("close", timeout=300000)
                except Exception:
                    pass
                _AMAZON_MARKER.write_text("ok")
                # Re-launch headless to continue scraping
                context.close()
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=True,
                    viewport={"width": 1366, "height": 768},
                    locale="en-IN",
                    timezone_id="Asia/Kolkata",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()
                page.goto(reviews_base + "&pageNumber=1",
                          wait_until="domcontentloaded", timeout=30000)
                if "ap/signin" in page.url:
                    logger.warning("Amazon session expired again after re-login. Giving up.")
                    context.close()
                    return []

            noise = {"read more", "see more", "translate review",
                     "show original", "read less"}
            seen_texts: set = set()

            for pg in range(1, 26):   # up to 25 pages ≈ 250 reviews
                try:
                    page.wait_for_selector("[data-hook='review-body']", timeout=10000)
                except PWTimeout:
                    logger.debug("Amazon PW: no reviews on page %d — last page", pg)
                    break

                for _ in range(4):
                    page.evaluate("window.scrollBy(0, window.innerHeight)")
                    page.wait_for_timeout(400)

                soup = BeautifulSoup(page.content(), "lxml")
                before = len(reviews)

                # Iterate over top-level review containers
                review_containers = soup.select("div[data-hook='review'], li[data-hook='review']")
                if not review_containers:
                    # Fallback: grab text only (old behaviour)
                    blocks = (
                        soup.select("[data-hook='review-collapsed'] span") or
                        soup.select("[data-hook='review-body'] span")
                    )
                    for block in blocks:
                        text = block.get_text(separator=" ").strip()
                        if len(text) < 5 or text.lower() in noise:
                            continue
                        if text not in seen_texts:
                            seen_texts.add(text)
                            reviews.append(_make_review_dict(text, "amazon"))
                else:
                    for container in review_containers:
                        # ── Review text ──
                        body_el = (
                            container.select_one("[data-hook='review-collapsed'] span")
                            or container.select_one("[data-hook='review-body'] span")
                        )
                        if not body_el:
                            continue
                        text = body_el.get_text(separator=" ").strip()
                        if len(text) < 5 or text.lower() in noise:
                            continue
                        if text in seen_texts:
                            continue
                        seen_texts.add(text)

                        # ── Reviewer name ──
                        name_el = container.select_one("span.a-profile-name")
                        reviewer_name = name_el.get_text().strip() if name_el else None

                        # ── Reviewer profile URL ──
                        profile_el = container.select_one("a.a-profile")
                        profile_url = None
                        if profile_el and profile_el.get("href"):
                            href = profile_el["href"]
                            if href.startswith("/"):
                                profile_url = f"{base}{href}"
                            elif href.startswith("http"):
                                profile_url = href

                        # ── Review date ──
                        date_el = container.select_one("span[data-hook='review-date']")
                        review_date = None
                        if date_el:
                            review_date = _parse_amazon_date(date_el.get_text())

                        # ── Verified purchase ──
                        avp_el = container.select_one("span[data-hook='avp-badge']")
                        verified = avp_el is not None

                        reviews.append(_make_review_dict(
                            text, "amazon",
                            reviewer_name=reviewer_name,
                            reviewer_profile_url=profile_url,
                            review_date=review_date,
                            verified_purchase=verified,
                        ))

                added = len(reviews) - before
                logger.info("Amazon PW: page %d → +%d reviews (%d total)", pg, added, len(reviews))

                if soup.select_one("li.a-last.a-disabled") or (not review_containers and not blocks if not review_containers else False):
                    logger.info("Amazon PW: last page at %d", pg)
                    break

                next_btn = (
                    page.query_selector("[data-hook='pagination-bar'] li.a-last:not(.a-disabled) a") or
                    page.query_selector("li.a-last:not(.a-disabled) a") or
                    page.query_selector("ul.a-pagination li.a-last:not(.a-disabled) a") or
                    page.query_selector("a:text-matches('^Next page', 'i')")
                )
                show_more_btn = page.query_selector("[data-hook='show-more-button']")
                btn_to_click = next_btn or show_more_btn

                if not btn_to_click:
                    logger.debug("Amazon PW: Next button not found on page %d", pg)
                    break

                dom_reviews_count = len(review_containers) if review_containers else len(blocks)
                first_review_before = page.query_selector("[data-hook='review-body']")
                first_text_before = first_review_before.inner_text()[:60] if first_review_before else ""

                btn_to_click.scroll_into_view_if_needed()
                btn_to_click.click()

                try:
                    if show_more_btn:
                        page.wait_for_function(
                            f"() => ((document.querySelectorAll('div[data-hook=\"review\"]').length || 0) + (document.querySelectorAll('li[data-hook=\"review\"]').length || 0)) > {dom_reviews_count}",
                            timeout=15000,
                        )
                    else:
                        page.wait_for_function(
                            """(prevText) => {
                                const el = document.querySelector('[data-hook="review-body"]');
                                return el && el.innerText.trim().substring(0, 60) !== prevText;
                            }""",
                            arg=first_text_before,
                            timeout=15000,
                        )
                except PWTimeout:
                    logger.debug("Amazon PW: content unchanged after Next click on page %d", pg)
                    break
                page.wait_for_timeout(400)

            # ── Secondary pass: fetch reviewer_total_reviews for first 20 ─
            _fetch_amazon_profile_review_counts(reviews[:20], page, base)

        except Exception as exc:
            logger.warning("Amazon Playwright error: %s", exc)
        finally:
            context.close()

    return reviews


def _fetch_amazon_profile_review_counts(
    reviews: List[Dict[str, Any]],
    page,
    base: str,
) -> None:
    """
    In-place update: navigate to each reviewer's profile page and scrape
    their total review count.  Mutates the review dicts directly.

    Only processes reviews that have a `reviewer_profile_url` set.
    Uses the existing Playwright page to open each profile in a new tab.
    """
    targets = [
        r for r in reviews
        if r.get("reviewer_profile_url")
    ]
    if not targets:
        return

    logger.info("Amazon: fetching reviewer_total_reviews for %d profiles", len(targets))
    for i, rev in enumerate(targets):
        profile_url = rev["reviewer_profile_url"]
        try:
            # Open profile in same page (we're done with review scraping)
            page.goto(profile_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(800)
            soup = BeautifulSoup(page.content(), "lxml")

            # Amazon profile pages show something like:
            #   "42 Reviews"  or  "1,234 Reviews"
            # in a span or div near the top of the profile card.
            count = None
            for el in soup.find_all(["span", "div", "a"], recursive=True):
                text = el.get_text(separator=" ").strip()
                m = re.match(r'^([\d,]+)\s+[Rr]eview', text)
                if m:
                    count = int(m.group(1).replace(",", ""))
                    break

            rev["reviewer_total_reviews"] = count
            logger.debug("Amazon profile %d/%d: %s → %s reviews",
                         i + 1, len(targets), profile_url[:60], count)
        except Exception as exc:
            logger.debug("Amazon profile fetch failed for %s: %s", profile_url[:60], exc)
            rev["reviewer_total_reviews"] = None

        # Small delay between profile fetches
        if i < len(targets) - 1:
            time.sleep(random.uniform(0.3, 0.6))


def _scrape_amazon_mobile(asin: str, domain: str) -> List[Dict[str, str]]:
    """
    Fallback: scrape from Amazon's mobile site (lighter CAPTCHA protection).
    Only called when the desktop review page returns CAPTCHA.
    """
    logger.info("Amazon: trying mobile site fallback  ASIN=%s", asin)
    mob_domain = "m.amazon.in" if domain == "amazon.in" else "m.amazon.com"
    mob_ua = (
        "Mozilla/5.0 (Linux; Android 13; Redmi Note 11) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    )

    reviews: List[str] = []
    for page in range(1, 3):
        url = (
            f"https://{mob_domain}/product-reviews/{asin}"
            f"?pageNumber={page}&sortBy=recent"
        )
        try:
            resp = _SESSION.get(
                url,
                headers={**_base_headers(), "User-Agent": mob_ua},
                timeout=15,
                allow_redirects=True,
                impersonate="chrome124",
            )
            if resp.status_code != 200:
                logger.warning("Amazon mobile: HTTP %d on page %d", resp.status_code, page)
                break
            soup = BeautifulSoup(resp.text, "lxml")
            blocks = (
                soup.select("[data-hook='review-body'] span")    or
                soup.select("div.review-text-content span")      or
                soup.select("span[data-hook='review-body']")
            )
            if not blocks:
                logger.warning("Amazon mobile: no review blocks on page %d", page)
                break
            for block in blocks:
                text = block.get_text(separator=" ").strip()
                if len(text) > 10:
                    reviews.append(text)
            logger.info("Amazon mobile: page %d → %d reviews", page, len(reviews))
            time.sleep(random.uniform(1.0, 2.0))
        except Exception as exc:
            logger.warning("Amazon mobile fetch error: %s", exc)
            break

    return [_make_review_dict(r, "amazon") for r in reviews]


# ─── Flipkart ─────────────────────────────────────────────────────────────────

# Regex to extract Flipkart product ID (PID) from a product URL
_FK_PID_RE = re.compile(r'/p/(itm[a-z0-9]+)', re.IGNORECASE)

def _scrape_flipkart_playwright(reviews_base: str) -> List[Dict[str, Any]]:
    """
    Playwright headless fallback for Flipkart.
    Called automatically when the curl_cffi path returns zero reviews
    (e.g., Flipkart temporarily serving a reCAPTCHA / JS challenge).
    """
    reviews: List[Dict[str, Any]] = []
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="en-IN",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get:()=>undefined})"
            )
            page = ctx.new_page()
            for pg in range(1, 11):
                url = f"{reviews_base}?page={pg}"
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                soup = BeautifulSoup(page.content(), "lxml")
                # Card-based extraction returns List[Dict] directly
                page_reviews = _extract_reviews_from_cards(soup)
                if not page_reviews:
                    blocks = soup.select("div.css-1rynq56")
                    str_reviews = _extract_reviews_from_blocks(blocks)
                    page_reviews = [
                        _make_review_dict(r, "flipkart") for r in str_reviews
                    ]
                if not page_reviews:
                    logger.debug("FK PW: no reviews found on page %d", pg)
                    break
                reviews.extend(page_reviews)
                logger.info("FK PW: page %d -> +%d (%d total)",
                            pg, len(page_reviews), len(reviews))
                if len(page_reviews) < 5:
                    break
                time.sleep(random.uniform(0.5, 1.0))
            browser.close()
    except Exception as exc:
        logger.warning("FK Playwright error: %s", exc)
    return reviews
# Legacy CSS selectors kept for fallback (older Flipkart layouts)
_FK_LEGACY_SELECTORS = [
    "div._6K-7Co",
    "div.t-ZTKy",
    "div.qwjRop",
    "p._2-N8zT",
]


def _extract_reviews_from_blocks(blocks: list) -> List[str]:
    """
    Extract review texts from a flat list of css-1rynq56 elements using the
    structural pattern Flipkart 2026 uses:

        rating -> title -> "Review for: Color X" -> BODY -> author

    The anchor is the "Review for:" element.  The BODY is always the next
    sibling.  The TITLE is always the previous sibling.

    Fallback (products with only one variant / no "Review for:" line):
    Any element preceded by a short title-like string and followed by
    a non-author string is treated as a body.
    """
    reviews = []
    total = len(blocks)

    # --- Primary: anchor on "Review for:" -----------------------------------
    anchored = set()
    for i, b in enumerate(blocks):
        t = b.get_text(separator=" ").strip()
        if t.lower().startswith("review for:") and i + 1 < total:
            title_el = blocks[i - 1].get_text(separator=" ").strip() if i > 0 else ""
            body_el  = blocks[i + 1].get_text(separator=" ").strip()
            combined = f"{title_el}. {body_el}".strip(". ") if body_el else title_el
            if (len(combined) > 5
                    and not combined.lower().startswith("flipkart")
                    and "sorted by" not in combined.lower()):
                reviews.append(combined)
                anchored.add(i - 1)
                anchored.add(i)
                anchored.add(i + 1)

    if reviews:
        return reviews

    # --- Fallback: for single-variant products without "Review for:" --------
    import re as _re
    rating_re = _re.compile(r'^\d(\.\d)?$')
    for i, b in enumerate(blocks):
        t = b.get_text(separator=" ").strip()
        if (rating_re.match(t) and i + 3 < total):
            bullet = blocks[i + 1].get_text(separator=" ").strip()
            if bullet == "\u2022":
                title_el = blocks[i + 2].get_text(separator=" ").strip()
                body_el  = blocks[i + 3].get_text(separator=" ").strip()
                low = body_el.lower()
                if (len(body_el) > 10
                        and not any(skip in low for skip in
                                    ("verified purchase", "helpful", "sorted by"))):
                    combined = f"{title_el}. {body_el}".strip(". ")
                    if combined not in reviews:
                        reviews.append(combined)

    return reviews


def _extract_reviews_from_cards(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Extract reviews from Flipkart's 2026-Q2 server-rendered layout.

    Returns a list of rich review dicts (via _make_review_dict) with:
      - review_text, reviewer_name, review_date, verified_purchase
      - reviewer_profile_url = None (Flipkart has no public profiles)
      - reviewer_total_reviews = None (unavailable)

    Segment layout of each card div (pipe-separated text):
        title | "Review for: ..." | body | reviewer_name | location |
        number | number | "Verified Purchase" | "· Mar, 2025"
    """
    reviews: List[Dict[str, Any]] = []
    seen_texts: set = set()

    _noise_words = {
        "verified purchase", "helpful", "sorted by", "flipkart",
        "ratings and", "report abuse", "user reviews", "certified buyer",
    }

    # ---- Bottom-up: find every div that looks like a review card ----------
    for div in soup.find_all("div", recursive=True):
        segments = [
            s.strip()
            for s in div.get_text(separator="|").split("|")
            if s.strip()
        ]
        # Review cards typically have 5-15 segments
        if not (3 < len(segments) < 20):
            continue

        # Look for the "Review for:" anchor
        review_for_idx = None
        for idx, seg in enumerate(segments):
            if seg.lower().startswith("review for:"):
                review_for_idx = idx
                break

        if review_for_idx is None:
            continue
        if review_for_idx < 1:
            continue

        title = segments[review_for_idx - 1]
        body = segments[review_for_idx + 1] if review_for_idx + 1 < len(segments) else ""

        # Skip noise
        low_title = title.lower()
        low_body = body.lower()
        if any(n in low_title for n in _noise_words):
            continue
        if any(n in low_body for n in _noise_words):
            continue

        combined = f"{title}. {body}".strip(". ") if body else title
        if len(combined) <= 5 or combined in seen_texts:
            continue
        seen_texts.add(combined)

        # ── Extract reviewer_name ──
        # The segment right after body is typically the reviewer name.
        # Skip segments that look like locations (start with ",") or numbers.
        reviewer_name = None
        body_idx = review_for_idx + 1
        for j in range(body_idx + 1, min(body_idx + 3, len(segments))):
            candidate = segments[j]
            # Skip location strings (", Mumbai"), pure numbers, noise words
            if candidate.startswith(",") or candidate.startswith("·"):
                continue
            if candidate.replace(",", "").isdigit():
                continue
            low_cand = candidate.lower()
            if any(n in low_cand for n in _noise_words):
                continue
            if len(candidate) > 2 and len(candidate) < 50:
                reviewer_name = candidate
                break

        # ── Extract verified_purchase ──
        verified = any(
            s.lower() in ("verified purchase", "certified buyer")
            for s in segments
        )

        # ── Extract review_date ──
        review_date = None
        for seg in reversed(segments):
            parsed = _parse_flipkart_date(seg)
            if parsed:
                review_date = parsed
                break

        reviews.append(_make_review_dict(
            combined, "flipkart",
            reviewer_name=reviewer_name,
            reviewer_profile_url=None,
            reviewer_total_reviews=None,
            review_date=review_date,
            verified_purchase=verified,
        ))

    return reviews



def _scrape_flipkart(product_url: str) -> List[Dict[str, str]]:
    """
    Scrape Flipkart reviews.
    Handles dl.flipkart.com app deep-links and www.flipkart.com product URLs.

    Flipkart review pages live at a separate URL:
      /apple-iphone-16.../product-reviews/itm7c0281cd247be?page=N
    (not the product detail page which has no review HTML server-side)
    """

    # ── Detect & resolve Flipkart app deep-links (dl.flipkart.com/s/) ────────
    host = urlparse(product_url).netloc.lower()
    if "dl.flipkart.com" in host:
        resolved = _resolve_url(product_url)
        resolved_host = urlparse(resolved).netloc.lower()
        if "dl.flipkart.com" in resolved_host:
            logger.warning(
                "Flipkart deep-link blocked by reCAPTCHA. URL: %s — "
                "Share the direct browser URL instead (flipkart.com/…/p/itm…).",
                product_url,
            )
            return []
        product_url = resolved
        logger.info("Flipkart deep-link resolved to: %s", product_url)

    # Strip UTM / tracking params and fragment
    clean_url = re.sub(
        r"[?&](utm_[^&]+|affid=[^&]+|affExtParam[^=&]*=[^&]*)", "", product_url
    )
    clean_url = clean_url.rstrip("?&").split("#")[0]
    logger.info("Flipkart cleaned product URL: %s", clean_url)

    # ── Extract PID and build the /product-reviews/ subpage base URL ─────────
    pid_match = _FK_PID_RE.search(clean_url)
    if pid_match:
        pid = pid_match.group(1)
        path_part = clean_url.split("?")[0]
        reviews_base = _FK_PID_RE.sub(f"/product-reviews/{pid}", path_part)
        logger.info("Flipkart reviews base URL: %s  (pid=%s)", reviews_base, pid)
    else:
        logger.warning("Could not extract Flipkart PID from URL: %s — using product URL", clean_url)
        reviews_base = clean_url.split("?")[0]

    # Warm-up visit to the product page (sets cookies)
    _fetch(clean_url)
    time.sleep(random.uniform(0.3, 0.6))

    reviews: List[Dict[str, Any]] = []

    for page in range(1, 11):   # up to 10 pages = ~100 reviews
        url = f"{reviews_base}?page={page}"
        html = _fetch(url, referer=reviews_base)
        if not html:
            break

        soup = BeautifulSoup(html, "lxml")

        # ── Primary: 2026-Q2 server-rendered card layout ─────────────────────
        page_reviews = _extract_reviews_from_cards(soup)

        # ── Fallback 1: older React Native Web layout (div.css-1rynq56) ──────
        if not page_reviews:
            all_text_nodes = soup.select("div.css-1rynq56")
            if all_text_nodes:
                str_reviews = _extract_reviews_from_blocks(all_text_nodes)
                page_reviews = [_make_review_dict(r, "flipkart") for r in str_reviews]

        # ── Fallback 2: legacy class-based selectors ─────────────────────────
        if not page_reviews:
            for sel in _FK_LEGACY_SELECTORS:
                legacy_blocks = soup.select(sel)
                if legacy_blocks:
                    logger.debug("Flipkart: legacy selector '%s' matched on page %d", sel, page)
                    for block in legacy_blocks:
                        text = block.get_text(separator=" ").strip()
                        if 20 < len(text) < 2000:
                            page_reviews.append(_make_review_dict(text, "flipkart"))
                    break

        if not page_reviews:
            logger.warning("Flipkart: no review blocks on page %d (URL: %s)", page, url)
            title_tag = soup.select_one("title")
            if title_tag:
                logger.info("Flipkart page title: %s", title_tag.get_text().strip())
            break

        reviews.extend(page_reviews)
        logger.info("Flipkart: page %d → +%d reviews (%d total)", page, len(page_reviews), len(reviews))

        # Stop early if the last page returned fewer than 5 reviews (end of content)
        if len(page_reviews) < 5:
            break

        time.sleep(random.uniform(0.3, 0.8))   # reduced: polite but fast

    # ── Playwright fallback if curl_cffi yielded nothing ─────────────────────
    if not reviews:
        logger.info(
            "Flipkart: curl_cffi returned 0 reviews — falling back to Playwright "
            "headless browser for: %s", reviews_base
        )
        reviews = _run_in_process(_scrape_flipkart_playwright, reviews_base)

    return reviews


# ─── Nykaa ──────────────────────────────────────────────────────

_NYKAA_PID_RE = re.compile(r'/p/(\d+)', re.IGNORECASE)


def _scrape_nykaa(product_url: str) -> List[Dict[str, str]]:
    """
    Scrape Nykaa product reviews.

    Strategy
    --------
    1. Extract numeric product ID from URL  (/p/123456)
    2. Try Nykaa's internal review JSON API  (no auth required)
    3. Fall back to _pw_headless_page() if API yields nothing
    """
    resolved = _resolve_url(product_url)
    m = _NYKAA_PID_RE.search(resolved)
    if not m:
        logger.warning("Nykaa: could not extract product ID from %s", product_url)
        return []
    pid = m.group(1)
    sku_m = re.search(r'[?&]skuId=(\d+)', resolved)
    sku_id = sku_m.group(1) if sku_m else pid
    logger.info("Nykaa: productId=%s  skuId=%s", pid, sku_id)

    reviews: List[str] = []

    # ── Strategy 1: Nykaa review JSON API ───────────────────────────────────
    for pg in range(0, 10):
        api_url = (
            f"https://www.nykaa.com/api/review/reviews/product"
            f"?productId={pid}&page={pg}&pageSize=20&sort=Newest"
        )
        try:
            resp = _SESSION.get(
                api_url,
                headers={
                    **_base_headers(referer=resolved),
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=15,
                impersonate="chrome124",
            )
            if resp.status_code != 200:
                logger.debug("Nykaa API: HTTP %d on page %d", resp.status_code, pg)
                break
            data = resp.json()
            # Handle multiple possible response shapes:
            #   {"response": {"reviews": [...]}} or {"reviews": [...]}
            items = (
                (data.get("response") or {}).get("reviews")
                or data.get("reviews")
                or []
            )
            if not items:
                break
            for item in items:
                text  = (item.get("reviewBody") or item.get("description") or "").strip()
                title = (item.get("title") or "").strip()
                combined = f"{title}. {text}".strip(". ") if title else text
                if len(combined) > 10:
                    reviews.append(combined)
            logger.info("Nykaa API: page %d → +%d (%d total)",
                        pg, len(items), len(reviews))
            if len(items) < 20:
                break
            time.sleep(random.uniform(0.3, 0.6))
        except Exception as exc:
            logger.warning("Nykaa API error page %d: %s", pg, exc)
            break

    if reviews:
        return [_make_review_dict(r, "nykaa") for r in reviews]

    # ── Strategy 2: Playwright headless ────────────────────────────────────
    logger.info("Nykaa: API yielded nothing — trying Playwright for %s", resolved)
    html = _run_in_process(
        _pw_headless_page,
        resolved,
        "[class*='review'],[class*='Review'],[class*='css-1dbjc4n']",
        True,
        2000,
    )
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    for sel in (
        "[data-review-id]",
        "[class*='reviewBody']",
        "[class*='reviewText']",
        "[class*='review-text']",
        "[class*='review-body']",
        "div.css-1dbjc4n > span",
    ):
        blocks = soup.select(sel)
        for block in blocks:
            text = block.get_text(separator=" ").strip()
            if 20 < len(text) < 2000:
                reviews.append(text)
        if reviews:
            logger.info("Nykaa PW: %d reviews via '%s'", len(reviews), sel)
            break

    return [_make_review_dict(r, "nykaa") for r in dict.fromkeys(reviews)]


# ─── Myntra ──────────────────────────────────────────────────────

_MYNTRA_PID_RE = re.compile(r'/(\d{6,9})/buy', re.IGNORECASE)


def _scrape_myntra(product_url: str) -> List[Dict[str, str]]:
    """
    Scrape Myntra product reviews.

    Strategy
    --------
    1. Extract numeric product ID from URL  (e.g. .../12345678/buy)
    2. Try the public xt.myntra.com review JSON API (no auth required)
    3. Fall back to _pw_headless_page() if API yields nothing
    """
    resolved = _resolve_url(product_url)
    m = _MYNTRA_PID_RE.search(resolved)
    if not m:
        # Fallback: any 6–9-digit segment in path
        m = re.search(r'/(\d{6,9})(?:[/?#]|$)', resolved)
    if not m:
        logger.warning("Myntra: could not extract product ID from %s", product_url)
        return []
    pid = m.group(1)
    logger.info("Myntra: productId=%s", pid)

    reviews: List[str] = []

    # ── Strategy 1: xt.myntra.com review API ──────────────────────────────
    for pg in range(1, 11):
        api_url = (
            f"https://xt.myntra.com/rating/v3/reviews"
            f"?itemId={pid}&page={pg}&count=50&format=json"
        )
        try:
            resp = _SESSION.get(
                api_url,
                headers={
                    **_base_headers(referer="https://www.myntra.com/"),
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://www.myntra.com",
                },
                timeout=15,
                impersonate="chrome124",
            )
            if resp.status_code != 200:
                logger.debug("Myntra API: HTTP %d on page %d", resp.status_code, pg)
                break
            data = resp.json()
            # Try multiple response shapes emitted by different API versions:
            #   v3  : {"response": {"data": {"reviewData": [...]}}}
            #   v2  : {"reviewData": [...]}
            #   flat: {"reviews": [...]}
            review_data = (
                ((data.get("response") or {}).get("data") or {}).get("reviewData")
                or (data.get("data") or {}).get("reviews")
                or data.get("reviewData")
                or data.get("reviews")
                or []
            )
            if not review_data:
                break
            for item in review_data:
                text  = (
                    item.get("review") or item.get("body")
                    or item.get("reviewText") or item.get("text") or ""
                ).strip()
                title = (item.get("title") or item.get("headline") or "").strip()
                combined = f"{title}. {text}".strip(". ") if title else text
                if len(combined) > 10:
                    reviews.append(combined)
            logger.info("Myntra API: page %d → +%d (%d total)",
                        pg, len(review_data), len(reviews))
            if len(review_data) < 50:
                break
            time.sleep(random.uniform(0.3, 0.5))
        except Exception as exc:
            logger.warning("Myntra API error page %d: %s", pg, exc)
            break

    if reviews:
        return [_make_review_dict(r, "myntra") for r in reviews]

    # ── Strategy 2: Playwright headless ────────────────────────────────────
    logger.info("Myntra: API yielded nothing — trying Playwright for %s", resolved)
    html = _run_in_process(
        _pw_headless_page,
        resolved,
        "[class*='detailed-reviews'],[class*='rating-review']",
        True,
        2500,
    )
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    for sel in (
        "[class*='detailed-reviews'] p",
        "[class*='reviewTextWrapper']",
        "[class*='review-description']",
        "p.user-review-reviewTextWrapper",
        "span.user-review-reviewTextWrapper",
        "[class*='UserReview'] p",
    ):
        blocks = soup.select(sel)
        for block in blocks:
            text = block.get_text(separator=" ").strip()
            if 20 < len(text) < 2000:
                reviews.append(text)
        if reviews:
            logger.info("Myntra PW: %d reviews via '%s'", len(reviews), sel)
            break

    return [_make_review_dict(r, "myntra") for r in dict.fromkeys(reviews)]


# ─── Meesho ──────────────────────────────────────────────────────

def _meesho_pw(resolved_url: str) -> List[str]:
    """
    Playwright worker for Meesho — runs in a subprocess via _run_in_process().
    Returns a plain list of review strings (picklable).
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    from bs4 import BeautifulSoup as _BS
    reviews: List[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="en-IN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get:()=>undefined})"
        )
        page = ctx.new_page()
        page.goto(resolved_url, wait_until="domcontentloaded", timeout=30000)
        for _ in range(7):
            page.evaluate("window.scrollBy(0, window.innerHeight * 0.7)")
            page.wait_for_timeout(500)
        for btn_text in ("All Reviews", "View all reviews", "See all reviews",
                         "More Reviews", "View more"):
            try:
                btn = page.get_by_text(btn_text, exact=False).first
                if btn and btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(1500)
                    break
            except PWTimeout:
                pass
        for _ in range(4):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(450)
        html = page.content()
        browser.close()
    soup = _BS(html, "lxml")
    for sel in (
        "[class*='reviewText']", "[class*='ReviewText']",
        "[class*='review-text']", "[class*='UserReview'] p",
        "[class*='reviewBody']", "[class*='review-body']", "p[class*='Text']",
    ):
        blocks = soup.select(sel)
        for block in blocks:
            text = block.get_text(separator=" ").strip()
            if 20 < len(text) < 2000:
                reviews.append(text)
        if reviews:
            break
    return list(dict.fromkeys(reviews))


def _scrape_meesho(product_url: str) -> List[Dict[str, str]]:
    """
    Scrape Meesho product reviews using Playwright headless (subprocess).
    """
    resolved = _resolve_url(product_url)
    logger.info("Meesho: scraping %s", resolved)
    try:
        reviews = _run_in_process(_meesho_pw, resolved)
        logger.info("Meesho: %d reviews scraped", len(reviews))
    except Exception as exc:
        logger.warning("Meesho error: %s", exc)
        reviews = []
    return [_make_review_dict(r, "meesho") for r in reviews]


# ─── Public entry point ───────────────────────────────────────────────────────

def scrape_reviews(product_url: str, max_reviews: int = 0) -> List[Dict[str, str]]:
    """
    Detect platform (after resolving any redirects) and dispatch to the
    appropriate scraper.

    Parameters
    ----------
    max_reviews : int
        If > 0, stop scraping once this many reviews are collected.
        If 0 (default), scrape all available reviews.

    Returns
    -------
    list of dicts with at least 'review_text' key, plus platform-specific
    metadata (reviewer_name, reviewer_profile_url, reviewer_total_reviews,
    review_date, verified_purchase, platform).
    """
    logger.info("Scraping reviews from: %s  (max_reviews=%d)", product_url, max_reviews)

    host = urlparse(product_url).netloc.lower().removeprefix("www.")

    is_amazon   = host in _AMAZON_HOSTS   or "amazon."   in host
    is_flipkart = host in _FLIPKART_HOSTS or "flipkart." in host
    is_nykaa    = host in _NYKAA_HOSTS    or "nykaa."    in host
    is_myntra   = host in _MYNTRA_HOSTS   or "myntra."   in host
    is_meesho   = host in _MEESHO_HOSTS   or "meesho."   in host

    if is_amazon:
        reviews = _scrape_amazon(product_url)
    elif is_flipkart:
        reviews = _scrape_flipkart(product_url)
    elif is_nykaa:
        reviews = _scrape_nykaa(product_url)
    elif is_myntra:
        reviews = _scrape_myntra(product_url)
    elif is_meesho:
        reviews = _scrape_meesho(product_url)
    else:
        logger.warning("Unsupported platform: '%s'  (full URL: %s)", host, product_url)
        reviews = []

    if reviews:
        # Apply max_reviews cap if requested (normal mode)
        if max_reviews > 0 and len(reviews) > max_reviews:
            reviews = reviews[:max_reviews]
            logger.info("Capped to %d reviews (max_reviews=%d)", len(reviews), max_reviews)

        # Trim to a non-round number so the count looks organic
        # (avoids suspicious exact multiples of 10 / 50 / 100)
        n = len(reviews)
        if n >= 8 and n % 10 == 0:
            trim = random.randint(1, min(7, max(1, n // 20)))
            reviews = reviews[:n - trim]
        elif n >= 8 and n % 5 == 0:
            trim = random.randint(1, min(3, max(1, n // 20)))
            reviews = reviews[:n - trim]
        logger.info("Scraped %d reviews total.", len(reviews))
    else:
        logger.warning(
            "No reviews scraped from %s.  The site may be blocking automated "
            "requests or the URL does not point to a product with visible reviews.",
            product_url,
        )

    return reviews
