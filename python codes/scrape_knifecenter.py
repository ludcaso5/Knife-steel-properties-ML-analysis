from __future__ import annotations

import hashlib
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.knifecenter.com"
STORE_URL = f"{BASE_URL}/kc_new/store_store.html"

# candidate site names to try
STEEL_GROUPS: dict[str, list[str]] = {
    "1,4116": ["1.4116", "4116"],
    "1095": ["1095"],
    "14C28N": ["14C28N"],
    "154CM": ["154CM"],
    "15V": ["15V"],
    "420HC": ["420HC"],
    "440A": ["440A"],
    "440C": ["440C"],
    "52100": ["52100"],
    "A2": ["A2"],
    "AEB-L": ["AEB-L"],
    "AUS-8 / 8Cr13MoV": ["AUS-8", "8Cr13MoV", "8Cr"],
    "CTS-BD1": ["CTS-BD1", "BD1"],
    "CTS-BD1N": ["CTS-BD1N", "BD1N"],
    "CTS-XHP": ["XHP", "CTS-XHP"],
    "D2": ["D2"],
    "Elmax": ["Elmax"],
    "H1": ["H1"],
    "K390": ["K390"],
    "LC200N": ["LC200N"],
    "M2": ["M2"],
    "M390 / PM-20CV / CTS-204P": ["M390", "20CV", "CPM-20CV", "204P", "CTS-204P"],
    "M398": ["M398"],
    "Maxamet": ["Maxamet"],
    "N690": ["N690"],
    "Nitro-V": ["Nitro-V"],
    "O1": ["O1"],
    "PM-10V": ["10V", "CPM-10V"],
    "PM-154": ["CPM-154"],
    "PM-3V": ["3V", "CPM-3V"],
    "PM-4V": ["4V", "CPM-4V"],
    "PM-CruWear": ["CRU-WEAR", "CPM-CruWear", "Cru-Wear"],
    "PM-M4": ["M4", "CPM-M4"],
    "PM-MagnaCut": ["MagnaCut", "CPM-MagnaCut"],
    "PM-S110V": ["S110V", "CPM-S110V"],
    "PM-S125V": ["S125V", "CPM-S125V"],
    "PM-S30V": ["S30V", "CPM-S30V"],
    "PM-S35VN": ["S35VN", "CPM-S35VN"],
    "PM-S45VN": ["S45VN", "CPM-S45VN"],
    "PM-S60V": ["S60V", "CPM-S60V"],
    "PM-S90V": ["S90V", "CPM-S90V"],
    "Rex 121": ["REX 121", "Rex 121"],
    "Rex 45/HAP40": ["REX 45", "Rex 45", "HAP40"],
    "Super Gold 2": ["SG2", "Super Gold 2", "Super Gold Powder Steel"],
    "Vanadis 8": ["Vanadis 8"],
    "Vanax": ["Vanax 37", "Vanax"],
    "VG-10": ["VG-10"],
    "ZDP-189": ["ZDP-189"],
    "Z-Max": ["Z-Max"],
    "Z-Tuff": ["Z-Tuff"],
}

STEEL_QUERY_OVERRIDES: dict[str, str] = {
    "1.4116": "1.4116",
    "4116": "4116",
    "14C28N": "14c28n",
    "AEB-L": "aeb-l",
    "AUS-8": "aus-8",
    "8Cr13MoV": "8cr13mov",
    "8Cr": "8cr",
    "CTS-BD1": "cts-bd1",
    "BD1": "cts-bd1",
    "CTS-BD1N": "cts-bd1n",
    "BD1N": "cts-bd1n",
    "XHP": "xhp",
    "CTS-XHP": "xhp",
    "CPM-154": "cpm-154",
    "CRU-WEAR": "cru-wear",
    "CPM-CruWear": "cru-wear",
    "Cru-Wear": "cru-wear",
    "Elmax": "elmax",
    "20CV": "20cv",
    "CPM-20CV": "20cv",
    "204P": "204p",
    "CTS-204P": "204p",
    "MagnaCut": "magnacut",
    "CPM-MagnaCut": "magnacut",
    "Nitro-V": "nitro-v",
    "10V": "10v",
    "CPM-10V": "10v",
    "3V": "3v",
    "CPM-3V": "3v",
    "4V": "4v",
    "CPM-4V": "4v",
    "S110V": "s110v",
    "CPM-S110V": "s110v",
    "S125V": "s125v",
    "CPM-S125V": "s125v",
    "S30V": "s30v",
    "CPM-S30V": "s30v",
    "S35VN": "s35vn",
    "CPM-S35VN": "s35vn",
    "S45VN": "s45vn",
    "CPM-S45VN": "s45vn",
    "S60V": "s60v",
    "CPM-S60V": "s60v",
    "S90V": "s90v",
    "CPM-S90V": "s90v",
    "REX 121": "rex-121",
    "Rex 121": "rex-121",
    "REX 45": "rex-45",
    "Rex 45": "rex-45",
    "HAP40": "hap40",
    "SG2": "sg2",
    "Super Gold 2": "super-gold-2",
    "Super Gold Powder Steel": "super-gold-powder-steel",
    "Vanadis 8": "vanadis-8",
    "Vanax 37": "vanax-37",
    "Vanax": "vanax-37",
    "VG-10": "vg-10",
    "ZDP-189": "zdp-189",
    "Z-Max": "z-max",
    "Z-Tuff": "z-tuff",
}

STEEL_SLUG_OVERRIDES: dict[str, str] = {
    "1.4116": "1-4116",
    "4116": "4116",
    "1095": "1095",
    "14C28N": "14c28n",
    "154CM": "154cm",
    "15V": "15v",
    "420HC": "420hc",
    "440A": "440a",
    "440C": "440c",
    "52100": "52100",
    "8Cr13MoV": "8cr13mov",
    "8Cr": "8cr",
    "A2": "a2",
    "AEB-L": "aeb-l",
    "AUS-8": "aus-8",
    "CTS-BD1": "cts-bd1",
    "BD1": "cts-bd1",
    "CTS-BD1N": "cts-bd1n",
    "BD1N": "cts-bd1n",
    "XHP": "xhp",
    "CTS-XHP": "xhp",
    "CPM-154": "cpm-154",
    "D2": "d2",
    "CRU-WEAR": "cru-wear",
    "CPM-CruWear": "cru-wear",
    "Cru-Wear": "cru-wear",
    "Elmax": "elmax",
    "H1": "h1",
    "HAP40": "hap40",
    "K390": "k390",
    "LC200N": "lc200n",
    "M2": "m2",
    "M390": "m390",
    "20CV": "20cv",
    "CPM-20CV": "20cv",
    "204P": "204p",
    "CTS-204P": "204p",
    "M398": "m398",
    "M4": "m4",
    "CPM-M4": "m4",
    "MagnaCut": "magnacut",
    "CPM-MagnaCut": "magnacut",
    "Maxamet": "maxamet",
    "N690": "n690",
    "Nitro-V": "nitro-v",
    "O1": "o1",
    "10V": "10v",
    "CPM-10V": "10v",
    "3V": "3v",
    "CPM-3V": "3v",
    "4V": "4v",
    "CPM-4V": "4v",
    "REX 121": "rex-121",
    "Rex 121": "rex-121",
    "REX 45": "rex-45",
    "Rex 45": "rex-45",
    "S110V": "s110v",
    "CPM-S110V": "s110v",
    "S125V": "s125v",
    "CPM-S125V": "s125v",
    "S30V": "s30v",
    "CPM-S30V": "s30v",
    "S35VN": "s35vn",
    "CPM-S35VN": "s35vn",
    "S45VN": "s45vn",
    "CPM-S45VN": "s45vn",
    "S60V": "s60v",
    "CPM-S60V": "s60v",
    "S90V": "s90v",
    "CPM-S90V": "s90v",
    "SG2": "sg2",
    "Super Gold 2": "super-gold-2",
    "Super Gold Powder Steel": "super-gold-powder-steel",
    "Vanadis 8": "vanadis-8",
    "Vanax 37": "vanax-37",
    "Vanax": "vanax-37",
    "VG-10": "vg-10",
    "ZDP-189": "zdp-189",
    "Z-Max": "z-max",
    "Z-Tuff": "z-tuff",
}

BASE_DIR = Path(__file__).resolve().parent

PRICE_WORKBOOK = BASE_DIR / "steel_price_data.xlsx"

SHEET_RAW = "KC_Raw"
SHEET_SUMMARY = "KC_Summary"
SHEET_UNRESOLVED = "KC_Unresolved"
SHEET_STATUS = "KC_Status"

CACHE_DIR = BASE_DIR / "cache_knifecenter"
CACHE_DIR.mkdir(exist_ok=True)

PRE_REQUEST_DELAY_RANGE = (10.0, 20.0)
POST_PAGE_DELAY_RANGE = (10.0, 20.0)
WARMUP_DELAY_RANGE = (15.0, 25.0)
BETWEEN_CANDIDATES_DELAY_RANGE = (30.0, 60.0)
BETWEEN_LISTINGS_DELAY_RANGE = (40.0, 80.0)
STEEL_COOLDOWN_RANGE = (100.0, 200.0)
RECOVERY_COOLDOWN_RANGE = (200.0, 400.0)
BLOCK_COOLDOWN_RANGE = (300.0, 600.0)
TIMEOUT = 45
MAX_PAGES_PER_LISTING = 40
MAX_MANUAL_RETRIES = 2
SESSION_RESET_EVERY_N_PAGES = 4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}


WARMED_CONTEXTS: set[str] = set()
PAGE_COUNTER = 0

def write_price_sheets(
    sheets: dict[str, pd.DataFrame],
) -> None:
    if PRICE_WORKBOOK.exists():
        with pd.ExcelWriter(
            PRICE_WORKBOOK,
            engine="openpyxl",
            mode="a",
            if_sheet_exists="replace",
        ) as writer:
            for sheet_name, frame in sheets.items():
                frame.to_excel(
                    writer,
                    sheet_name=sheet_name,
                    index=False,
                )
    else:
        with pd.ExcelWriter(
            PRICE_WORKBOOK,
            engine="openpyxl",
            mode="w",
        ) as writer:
            for sheet_name, frame in sheets.items():
                frame.to_excel(
                    writer,
                    sheet_name=sheet_name,
                    index=False,
                )


def read_price_sheet(
    sheet_name: str,
) -> pd.DataFrame:
    if not PRICE_WORKBOOK.exists():
        return pd.DataFrame()

    try:
        return pd.read_excel(
            PRICE_WORKBOOK,
            sheet_name=sheet_name,
        )
    except (
        ValueError,
        FileNotFoundError,
    ):
        return pd.DataFrame()
@dataclass
class FetchResult:
    response: requests.Response | None
    blocked: bool = False
    error: str | None = None
    from_cache: bool = False


@dataclass
class ListingResult:
    rows: list[dict[str, Any]]
    status: str
    pages_scraped: int
    blocked_page: int | None = None
    message: str | None = None
    site_steel_name: str | None = None


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=0,
        connect=0,
        read=0,
        backoff_factor=0,
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=1, pool_maxsize=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)
    return session


SESSION = build_session()
MEMORY_CACHE: dict[str, str] = {}


def reset_session() -> None:
    global SESSION, WARMED_CONTEXTS, PAGE_COUNTER
    try:
        SESSION.close()
    except Exception:
        pass
    SESSION = build_session()
    WARMED_CONTEXTS.clear()
    PAGE_COUNTER = 0


def sleep_range(bounds: tuple[float, float], label: str | None = None) -> None:
    seconds = random.uniform(*bounds)
    if label:
        print(f"[SLEEP] {label}: {seconds:.1f}s")
    time.sleep(seconds)


def clean_text(text: str) -> str:
    return " ".join(text.split()).strip()


def cache_path_for_url(url: str) -> Path:
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.html"


def load_cached_text(url: str) -> str | None:
    if url in MEMORY_CACHE:
        return MEMORY_CACHE[url]
    path = cache_path_for_url(url)
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="ignore")
        MEMORY_CACHE[url] = text
        return text
    return None


def save_cached_text(url: str, text: str) -> None:
    MEMORY_CACHE[url] = text
    cache_path_for_url(url).write_text(text, encoding="utf-8")


def steel_to_slug(steel: str) -> str:
    if steel in STEEL_SLUG_OVERRIDES:
        return STEEL_SLUG_OVERRIDES[steel]
    slug = steel.lower().strip()
    slug = slug.replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def steel_to_query_value(steel: str) -> str:
    return STEEL_QUERY_OVERRIDES.get(steel, steel)


def build_listing_url(steel: str, listing_filter: str, page: int = 1) -> str:
    params = [f"a={listing_filter}", f"steel={quote_plus(steel_to_query_value(steel))}"]
    if page > 1:
        params.append(f"page={page}")
    return f"{STORE_URL}?{'&'.join(params)}"

def bootstrap_listing_context(listing_filter: str) -> None:
    global WARMED_CONTEXTS
    if listing_filter in WARMED_CONTEXTS:
        return
    warmup_urls = {
        "folder": [f"{BASE_URL}/shop/knives", f"{BASE_URL}/listing/all-folding-knives"],
        "fixed": [f"{BASE_URL}/shop/knives", f"{BASE_URL}/listing/fixed-blade-knives"],
        "general": [f"{BASE_URL}/shop/knives", f"{BASE_URL}/listing/knives-with-14c28n-steel"],
    }
    for url in warmup_urls.get(listing_filter, []):
        if load_cached_text(url) is not None:
            continue
        try:
            sleep_range(WARMUP_DELAY_RANGE, f"warmup before {listing_filter}")
            resp = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
            if resp.ok and resp.text:
                save_cached_text(url, resp.text)
            sleep_range(WARMUP_DELAY_RANGE, f"warmup after {listing_filter}")
        except requests.RequestException:
            break
    WARMED_CONTEXTS.add(listing_filter)


def maybe_reset_session_after_page() -> None:
    global PAGE_COUNTER
    PAGE_COUNTER += 1
    if PAGE_COUNTER % SESSION_RESET_EVERY_N_PAGES == 0:
        sleep_range(BETWEEN_LISTINGS_DELAY_RANGE, "before session reset")
        print("[SESSION] reset after several pages")
        reset_session()


def fetch(url: str, referer: str | None = None, warmup_filter: str | None = None) -> FetchResult:
    cached_text = load_cached_text(url)
    if cached_text is not None:
        return FetchResult(response=None, from_cache=True)
    if warmup_filter:
        bootstrap_listing_context(warmup_filter)
    last_error: str | None = None
    for attempt in range(MAX_MANUAL_RETRIES + 1):
        try:
            headers = dict(HEADERS)
            if referer:
                headers["Referer"] = referer
            sleep_range(PRE_REQUEST_DELAY_RANGE, f"before GET {url}")
            resp = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True, headers=headers)
            maybe_reset_session_after_page()
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < MAX_MANUAL_RETRIES:
                sleep_range(RECOVERY_COOLDOWN_RANGE, f"network retry {attempt + 1}")
                reset_session()
                continue
            return FetchResult(response=None, blocked=False, error=last_error)

        if resp.status_code in {403, 429}:
            retry_after = resp.headers.get("Retry-After")
            cooldown = None
            if retry_after and retry_after.isdigit():
                cooldown = max(float(retry_after), random.uniform(*BLOCK_COOLDOWN_RANGE))
            else:
                cooldown = random.uniform(*BLOCK_COOLDOWN_RANGE)
            print(f"[BLOCK] {url} -> HTTP {resp.status_code}; cooling down {cooldown:.1f}s")
            time.sleep(cooldown)
            reset_session()
            return FetchResult(response=None, blocked=True, error=f"HTTP {resp.status_code}")

        if resp.status_code in {500, 502, 503, 504}:
            last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_MANUAL_RETRIES:
                sleep_range(RECOVERY_COOLDOWN_RANGE, f"server retry {attempt + 1}")
                reset_session()
                continue
            return FetchResult(response=None, blocked=False, error=last_error)

        try:
            resp.raise_for_status()
        except requests.RequestException as exc:
            return FetchResult(response=resp, blocked=False, error=str(exc))

        save_cached_text(url, resp.text)
        sleep_range(POST_PAGE_DELAY_RANGE, f"after GET {url}")
        return FetchResult(response=resp)

    return FetchResult(response=None, blocked=False, error=last_error or "unknown fetch error")


def soup_from_url(url: str, referer: str | None = None, warmup_filter: str | None = None) -> tuple[BeautifulSoup | None, FetchResult]:
    result = fetch(url, referer=referer, warmup_filter=warmup_filter)
    text = load_cached_text(url)
    if text is not None:
        return BeautifulSoup(text, "html.parser"), result
    if result.response is None:
        return None, result
    return BeautifulSoup(result.response.text, "html.parser"), result


def get_listing_product_anchors(soup: BeautifulSoup) -> list[Any]:
    out: list[Any] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if "/item/" not in href:
            continue
        text = clean_text(" ".join(a.stripped_strings))
        if not text:
            continue
        text_l = text.lower()
        if "our price" not in text_l and "retail price" not in text_l and "special" not in text_l and "$" not in text:
            continue
        out.append(a)
    return out


def parse_price_from_text(text: str) -> float | None:
    text = clean_text(text)
    patterns = [
        r"(?:our price|special)\s*:?\s*\$([0-9][0-9,]*(?:\.\d{2})?)",
        r"(?:price)\s*:?\s*\$([0-9][0-9,]*(?:\.\d{2})?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return float(m.group(1).replace(",", ""))
    prices = re.findall(r"\$([0-9][0-9,]*(?:\.\d{2})?)", text)
    return float(prices[-1].replace(",", "")) if prices else None


def extract_title_from_listing_anchor_text(text: str) -> str:
    text = clean_text(text)
    m = re.search(r"^(.*?)(?:Retail price:|Our Price:|Special:|\$[0-9])", text, flags=re.I)
    return m.group(1).strip(" -|") if m else text.strip()


def detect_knife_type_from_title(title: str) -> str:
    t = title.lower()
    fixed_markers = [
        "fixed blade", "neck knife", "bushcraft", "camp knife", "boot knife",
        "dagger", "machete", "karambit fixed", "pocket fixed blade",
        "utility knife fixed", "skinner fixed", "survival knife", "throwing knife",
        "fillet knife fixed",
    ]
    folding_markers = [
        "folding knife", "assisted folding knife", "assisted flipper knife", "assisted knife",
        "folder", "locking folder", "flipper", "front flipper", "liner lock", "frame lock",
        "button lock", "lockback", "back lock", "crossbar lock", "crossbar", "axis lock",
        "axis", "shark lock", "compression lock", "slipjoint", "slip joint", "auto folding",
        "automatic folding", "otf", "out the front", "balisong", "butterfly knife", "stiletto",
        "canoe", "stockman", "trapper", "whittler", "barlow", "copperlock", "peanut",
        "sodbuster", "jack knife", "pocket knife",
    ]
    if any(m in t for m in fixed_markers):
        return "fixed"
    if any(m in t for m in folding_markers):
        return "folding"
    return "unknown"


def is_probably_no_results_page(soup: BeautifulSoup) -> bool:
    text = clean_text(soup.get_text(" ", strip=True)).lower()
    return any(marker in text for marker in ["0 results", "no products found", "no results", "your search returned no results"])


def dedupe_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("steel_group", "")), str(row.get("knife_type", "")), str(row.get("product_url", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def iter_listing_products_for_site_name(steel_group: str, site_steel_name: str, listing_filter: str, output_knife_type: str, max_pages: int = MAX_PAGES_PER_LISTING) -> ListingResult:
    seen_urls: set[str] = set()
    rows: list[dict[str, Any]] = []
    pages_scraped = 0
    referer_map = {
        "folder": f"{BASE_URL}/listing/all-folding-knives",
        "fixed": f"{BASE_URL}/listing/fixed-blade-knives",
    }
    referer = referer_map.get(listing_filter, f"{BASE_URL}/shop/knives")

    for page_num in range(1, max_pages + 1):
        page_url = build_listing_url(site_steel_name, listing_filter, page=page_num)
        print(f"[PAGE] {steel_group} -> {site_steel_name} | {listing_filter} | page {page_num}")
        soup, fetch_result = soup_from_url(page_url, referer=referer, warmup_filter=listing_filter)

        if fetch_result.blocked:
            return ListingResult(rows=rows, status="partial_blocked" if rows else "blocked", pages_scraped=pages_scraped, blocked_page=page_num, message=fetch_result.error, site_steel_name=site_steel_name)
        if soup is None:
            return ListingResult(rows=rows, status="error" if not rows else "partial_blocked", pages_scraped=pages_scraped, blocked_page=page_num, message=fetch_result.error, site_steel_name=site_steel_name)

        anchors = get_listing_product_anchors(soup)
        page_new_count = 0
        for a in anchors:
            href = a.get("href", "").strip()
            product_url = urljoin(BASE_URL, href)
            if product_url in seen_urls:
                continue
            anchor_text = clean_text(" ".join(a.stripped_strings))
            price = parse_price_from_text(anchor_text)
            if price is None:
                continue
            title = extract_title_from_listing_anchor_text(anchor_text)
            if len(title) < 8:
                continue
            canonical_type = output_knife_type if output_knife_type != "unknown" else detect_knife_type_from_title(title)
            seen_urls.add(product_url)
            page_new_count += 1
            rows.append({
                "steel_group": steel_group,
                "site_steel_name": site_steel_name,
                "knife_type": canonical_type,
                "price_usd": price,
                "title": title,
                "product_url": product_url,
                "listing_url": page_url,
            })

        pages_scraped += 1
        print(f"[PAGE OK] {steel_group} -> {site_steel_name} | {listing_filter} | page {page_num} | +{page_new_count}")
        if page_new_count == 0:
            if page_num == 1 and is_probably_no_results_page(soup):
                return ListingResult(rows=[], status="empty", pages_scraped=pages_scraped, site_steel_name=site_steel_name)
            return ListingResult(rows=rows, status="success", pages_scraped=pages_scraped, site_steel_name=site_steel_name)

    return ListingResult(rows=rows, status="success", pages_scraped=pages_scraped, message=f"max_pages reached ({max_pages})", site_steel_name=site_steel_name)


def try_site_names(steel_group: str, listing_filter: str, output_knife_type: str) -> ListingResult:
    candidates = STEEL_GROUPS[steel_group]
    best = ListingResult(rows=[], status="empty", pages_scraped=0, message="no candidate tried")
    for idx, site_steel_name in enumerate(candidates, start=1):
        print(f"[CANDIDATE] {steel_group} | trying site name {idx}/{len(candidates)}: {site_steel_name}")
        result = iter_listing_products_for_site_name(steel_group, site_steel_name, listing_filter, output_knife_type)
        if result.rows:
            return result
        if result.status in {"blocked", "partial_blocked", "error"}:
            best = result
            if result.status == "blocked":
                sleep_range(BLOCK_COOLDOWN_RANGE, f"after block on {steel_group}/{site_steel_name}")
                reset_session()
        else:
            best = result
        if idx < len(candidates):
            sleep_range(BETWEEN_CANDIDATES_DELAY_RANGE, f"between steel aliases for {steel_group}")
            reset_session()
    return best


def remove_high_outliers(series: pd.Series, max_fraction_to_trim: float = 0.1) -> pd.Series:
    if series.empty or len(series) <= 1:
        return series
    k = max(1, int(round(len(series) * max_fraction_to_trim)))
    return series.sort_values().reset_index(drop=True).iloc[:-k]


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    usable = df[df["knife_type"].isin(["folding", "fixed"])].copy()
    grouped = (
        usable.groupby(["steel_group", "knife_type"])["price_usd"]
        .apply(lambda s: remove_high_outliers(s).mean())
        .reset_index(name="mean_price_usd")
    )
    wide = grouped.pivot(index="steel_group", columns="knife_type", values="mean_price_usd").reset_index()
    wide.columns.name = None
    for col in ["folding", "fixed"]:
        if col not in wide.columns:
            wide[col] = pd.NA
    return wide[["steel_group", "folding", "fixed"]].sort_values("steel_group").reset_index(drop=True)


def save_progress(
    all_rows: list[dict[str, Any]],
    unresolved: list[str],
    status_rows: list[dict[str, Any]],
) -> None:
    sheets: dict[str, pd.DataFrame] = {
        SHEET_UNRESOLVED: pd.DataFrame(
            {
                "steel_group": sorted(
                    set(unresolved)
                )
            }
        ),
        SHEET_STATUS: pd.DataFrame(status_rows),
    }

    if all_rows:
        raw_df = (
            pd.DataFrame(all_rows)
            .drop_duplicates(
                subset=[
                    "steel_group",
                    "knife_type",
                    "product_url",
                ]
            )
            .copy()
        )

        raw_df = raw_df[
            [
                "steel_group",
                "site_steel_name",
                "knife_type",
                "price_usd",
                "title",
                "product_url",
                "listing_url",
            ]
        ].sort_values(
            [
                "steel_group",
                "knife_type",
                "price_usd",
                "title",
            ]
        ).reset_index(drop=True)

        sheets[SHEET_RAW] = raw_df
        sheets[SHEET_SUMMARY] = build_summary(raw_df)

    write_price_sheets(sheets)

def load_resume_state() -> tuple[
    list[dict[str, Any]],
    list[str],
    list[dict[str, Any]],
    set[str],
]:
    raw_df = read_price_sheet(SHEET_RAW)

    unresolved_df = read_price_sheet(
        SHEET_UNRESOLVED
    )

    status_df = read_price_sheet(
        SHEET_STATUS
    )

    all_rows = (
        raw_df.to_dict("records")
        if not raw_df.empty
        else []
    )

    unresolved = (
        unresolved_df["steel_group"]
        .dropna()
        .astype(str)
        .tolist()
        if "steel_group" in unresolved_df.columns
        else []
    )

    status_rows = (
        status_df.to_dict("records")
        if not status_df.empty
        else []
    )

    if {
        "steel_group",
        "overall_status",
    }.issubset(status_df.columns):
        success_mask = (
            status_df["overall_status"]
            .astype(str)
            .str.lower()
            .eq("success")
        )

        already_done = set(
            status_df.loc[success_mask, "steel_group"]
            .dropna()
            .astype(str)
        )
    else:
        already_done = set()

    return (
        all_rows,
        unresolved,
        status_rows,
        already_done,
    )


def main() -> None:
    groups_to_process = list(STEEL_GROUPS.keys())
    all_rows, unresolved, status_rows, already_done = load_resume_state()
    remaining = [g for g in groups_to_process if g not in already_done]

    print(f"[INFO] Number of steel groups total : {len(groups_to_process)}")
    print(f"[INFO] Already processed groups    : {len(already_done)}")
    print(f"[INFO] Remaining groups            : {len(remaining)}")

    for idx, steel_group in enumerate(remaining, start=1):
        print(f"\n=== {steel_group} ({idx}/{len(remaining)}) ===")
        try:
            folding_result = try_site_names(steel_group, listing_filter="folder", output_knife_type="folding")
            print(f"[OK] Folding status: {folding_result.status} | rows={len(folding_result.rows)} | site_name={folding_result.site_steel_name}")

            sleep_range(BETWEEN_LISTINGS_DELAY_RANGE, f"between folder and fixed for {steel_group}")
            reset_session()

            fixed_result = try_site_names(steel_group, listing_filter="fixed", output_knife_type="fixed")
            print(f"[OK] Fixed status  : {fixed_result.status} | rows={len(fixed_result.rows)} | site_name={fixed_result.site_steel_name}")

            steel_rows = dedupe_rows(folding_result.rows + fixed_result.rows)
            if steel_rows:
                all_rows.extend(steel_rows)

            overall_status = "success" if (folding_result.rows or fixed_result.rows) else ("blocked" if "blocked" in {folding_result.status, fixed_result.status} else "empty")
            status_rows.append({
                "steel_group": steel_group,
                "folder_site_steel_name": folding_result.site_steel_name,
                "folding_status": folding_result.status,
                "folding_count": len(folding_result.rows),
                "folding_pages_scraped": folding_result.pages_scraped,
                "folding_blocked_page": folding_result.blocked_page,
                "folding_message": folding_result.message,
                "fixed_site_steel_name": fixed_result.site_steel_name,
                "fixed_status": fixed_result.status,
                "fixed_count": len(fixed_result.rows),
                "fixed_pages_scraped": fixed_result.pages_scraped,
                "fixed_blocked_page": fixed_result.blocked_page,
                "fixed_message": fixed_result.message,
                "overall_status": overall_status,
            })

            if overall_status != "success":
                unresolved.append(steel_group)
                print(f"[WARN] unresolved: {steel_group} ({overall_status})")
            else:
                unresolved = [
                    group
                    for group in unresolved
                    if group != steel_group
                ]
                print(f"[OK] processed: {steel_group}")

            save_progress(all_rows, unresolved, status_rows)
            sleep_range(STEEL_COOLDOWN_RANGE, f"between steel groups after {steel_group}")
            reset_session()

        except Exception as exc:
            print(f"[ERROR GROUP] {steel_group} -> {exc}")
            unresolved.append(steel_group)
            status_rows.append({
                "steel_group": steel_group,
                "folding_status": "error",
                "folding_count": 0,
                "folding_pages_scraped": 0,
                "folding_blocked_page": None,
                "folding_message": str(exc),
                "fixed_status": "error",
                "fixed_count": 0,
                "fixed_pages_scraped": 0,
                "fixed_blocked_page": None,
                "fixed_message": str(exc),
                "overall_status": "error",
            })
            save_progress(all_rows, unresolved, status_rows)
            sleep_range(RECOVERY_COOLDOWN_RANGE, f"recovery after error on {steel_group}")
            reset_session()

    if not all_rows:
        print("\nNo data collected.")
        save_progress(all_rows, unresolved, status_rows)
        return

    print("\n====================")
    print("Export complete")
    print("====================")
    print(
        f"Price workbook  : "
        f"{PRICE_WORKBOOK.resolve()}"
    )


if __name__ == "__main__":
    main()
