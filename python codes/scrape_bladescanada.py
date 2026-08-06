from __future__ import annotations

import hashlib
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.bladescanada.com"
SEARCH_PATH = "/index.php"

# candidate aliases to search on Blades Canada.
STEEL_GROUPS: dict[str, list[str]] = {
    "1,4116": ["1.4116", "4116"],
    "1095": ["1095", "1095 Carbon"],
    "14C28N": ["14C28N", "Sandvik 14C28N"],
    "154CM": ["154CM", "154 CM"],
    "15V": ["15V", "CPM 15V"],
    "420HC": ["420HC"],
    "440A": ["440A", "440 Stainless"],
    "440C": ["440C"],
    "52100": ["52100"],
    "A2": ["A2", "A-2"],
    "AEB-L": ["AEB-L"],
    "AUS-8 / 8Cr13MoV": ["AUS-8", "AUS 8", "8Cr13MoV", "8Cr", "CrMoV"],
    "CTS-BD1": ["CTS-BD1", "CTS BD1", "BD1"],
    "CTS-BD1N": ["CTS-BD1N", "CTS BD1N", "BD1N"],
    "CTS-XHP": ["CTS-XHP", "CTS XHP", "XHP"],
    "D2": ["D2"],
    "Elmax": ["Elmax"],
    "H1": ["H1", "H-1"],
    "K390": ["K390"],
    "LC200N": ["LC200N"],
    "M2": ["M2"],
    "M390 / PM-20CV / CTS-204P": [
        "M390",
        "M390/M398",
        "20CV",
        "CPM 20CV",
        "CTS 204P",
        "204P",
    ],
    "M398": ["M398", "M390/M398"],
    "Maxamet": ["Maxamet"],
    "N690": ["N690", "N690-95"],
    "Nitro-V": ["Nitro-V", "Nitro V"],
    "O1": ["O1", "O-1"],
    "PM-10V": ["10V", "CPM 10V"],
    "PM-154": ["CPM 154", "CPM-154", "154CM", "154 CM"],
    "PM-3V": ["3V", "CPM 3V"],
    "PM-4V": ["4V", "CPM 4V"],
    "PM-CruWear": ["CruWear", "Cru-Wear", "CRU-WEAR", "CPM CRU-WEAR"],
    "PM-M4": ["M4", "CPM M4"],
    "PM-MagnaCut": ["MagnaCut", "CPM MagnaCut"],
    "PM-S110V": ["S110V", "CPM S110V"],
    "PM-S125V": ["S125V", "CPM S125V"],
    "PM-S30V": ["S30V", "CPM S30V"],
    "PM-S35VN": ["S35VN", "CPM S35VN"],
    "PM-S45VN": ["S45VN", "CPM S45VN"],
    "PM-S60V": ["S60V", "CPM S60V"],
    "PM-S90V": ["S90V", "CPM S90V"],
    "Rex 121": ["REX 121", "Rex 121", "REX121"],
    "Rex 45/HAP40": ["REX 45", "Rex 45", "REX45", "HAP40"],
    "Super Gold 2": ["SG2", "SPG2", "Super Gold 2", "Super Gold Powder Steel"],
    "Vanadis 8": ["Vanadis 8"],
    "Vanax": ["Vanax", "Vanax 37"],
    "VG-10": ["VG-10", "VG10"],
    "ZDP-189": ["ZDP-189"],
    "Z-Max": ["Z-Max", "ZMax"],
    "Z-Tuff": ["Z-Tuff", "ZTuff"],
}

BASE_DIR = Path(__file__).resolve().parent

PRICE_WORKBOOK = BASE_DIR / "steel_price_data.xlsx"

SHEET_RAW = "BC_Raw"
SHEET_SUMMARY = "BC_Summary"
SHEET_UNRESOLVED = "BC_Unresolved"
SHEET_STATUS = "BC_Status"

CACHE_DIR = BASE_DIR / "cache_bladescanada"
CACHE_DIR.mkdir(exist_ok=True)

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
}

PRE_REQUEST_DELAY_RANGE = (1.5, 3.0)
POST_PAGE_DELAY_RANGE = (1.0, 2.0)
BETWEEN_ALIASES_DELAY_RANGE = (2.0, 4.0)
BETWEEN_STEELS_DELAY_RANGE = (5.0, 8.0)
RECOVERY_COOLDOWN_RANGE = (8.0, 15.0)

TIMEOUT = 35
MAX_PAGES_PER_ALIAS = 30
MAX_MANUAL_RETRIES = 2

SESSION: requests.Session | None = None
MEMORY_CACHE: dict[str, str] = {}

PRICE_RE = re.compile(r"\$([0-9][0-9,]*(?:\.\d{2})?)\s*CDN", re.I)

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
class ListingStatus:
    steel_group: str
    status: str
    pages_scraped: int
    product_count: int
    message: str | None = None


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


def get_session() -> requests.Session:
    global SESSION
    if SESSION is None:
        SESSION = build_session()
    return SESSION


def reset_session() -> None:
    global SESSION
    if SESSION is not None:
        try:
            SESSION.close()
        except (requests.RequestException, OSError, RuntimeError):
            pass
    SESSION = build_session()


reset_session()


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
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            MEMORY_CACHE[url] = text
            return text
        except (OSError, UnicodeError):
            return None
    return None


def save_cached_text(url: str, text: str) -> None:
    MEMORY_CACHE[url] = text
    cache_path_for_url(url).write_text(text, encoding="utf-8")


def build_keyword_search_url(keyword: str, page: int = 1) -> str:
    params: dict[str, str] = {
        "main_page": "search_result",
        "search_in_description": "1",
        "keyword": keyword,
    }
    if page > 1:
        params["page"] = str(page)
    return f"{BASE_URL}{SEARCH_PATH}?{urlencode(params)}"


def fetch(url: str, referer: str | None = None) -> FetchResult:
    cached_text = load_cached_text(url)
    if cached_text is not None:
        return FetchResult(response=None, from_cache=True)

    last_error: str | None = None
    session = get_session()

    for attempt in range(MAX_MANUAL_RETRIES + 1):
        try:
            headers = dict(HEADERS)
            if referer:
                headers["Referer"] = referer

            sleep_range(PRE_REQUEST_DELAY_RANGE, f"before GET {url}")
            resp = session.get(url, timeout=TIMEOUT, allow_redirects=True, headers=headers)

        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < MAX_MANUAL_RETRIES:
                sleep_range(RECOVERY_COOLDOWN_RANGE, f"network retry {attempt + 1}")
                reset_session()
                session = get_session()
                continue
            return FetchResult(response=None, blocked=False, error=last_error)

        if resp.status_code in {403, 429}:
            return FetchResult(response=None, blocked=True, error=f"HTTP {resp.status_code}")

        if resp.status_code in {500, 502, 503, 504}:
            last_error = f"HTTP {resp.status_code}"
            if attempt < MAX_MANUAL_RETRIES:
                sleep_range(RECOVERY_COOLDOWN_RANGE, f"server retry {attempt + 1}")
                reset_session()
                session = get_session()
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


def soup_from_url(url: str, referer: str | None = None) -> tuple[BeautifulSoup | None, FetchResult]:
    result = fetch(url, referer=referer)
    text = load_cached_text(url)
    if text is not None:
        return BeautifulSoup(text, "html.parser"), result
    if result.response is None:
        return None, result
    return BeautifulSoup(result.response.text, "html.parser"), result


def parse_price_from_text(text: str) -> float | None:
    text = clean_text(text)
    prices = PRICE_RE.findall(text)
    if not prices:
        return None

    return float(prices[-1].replace(",", ""))


def normalize_for_match(text: str) -> str:
    text = text.lower()
    text = text.replace("®", "")
    text = text.replace("-", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def alias_to_regex(alias: str) -> re.Pattern[str]:
    alias = alias.lower().strip()
    alias = alias.replace("®", "")
    alias = alias.replace("-", "-").replace("–", "-").replace("—", "-")
    alias = re.escape(alias)
    alias = alias.replace(r"\ ", r"[\s\-/]*")
    alias = alias.replace(r"\-", r"[\s\-/]*")
    return re.compile(rf"(?<![a-z0-9]){alias}(?![a-z0-9])", re.I)


def matches_alias(text: str, alias: str) -> bool:
    return bool(alias_to_regex(alias).search(text))


def detect_knife_type_from_title(title: str) -> str:
    t = normalize_for_match(title)

    fixed_markers = [
        "fixed blade",
        "fixed",
        "dagger",
        "neck knife",
        "bushcraft",
        "bowie",
        "machete",
        "skinner",
        "fillet knife",
        "boot knife",
        "karambit",
        "kunai",
    ]
    folding_markers = [
        "folding knife",
        "folding",
        "folder",
        "flipper",
        "slipjoint",
        "slip joint",
        "lockback",
        "back lock",
        "liner lock",
        "frame lock",
        "compression lock",
        "button lock",
        "crossbar lock",
        "axis lock",
        "otf",
        "out the front",
        "balisong",
        "butterfly knife",
        "assisted opening",
        "assisted",
    ]

    if any(marker in t for marker in fixed_markers):
        return "fixed"
    if any(marker in t for marker in folding_markers):
        return "folding"
    return "unknown"


def is_probable_product_title(title: str) -> bool:
    title = clean_text(title)
    if len(title) < 12:
        return False

    bad_exact = {
        "Buy Now",
        "... more info",
        "Home",
        "New Arrivals",
        "Specials",
        "Advanced Search",
        "My Account",
        "Sign In/Sign Up",
    }
    if title in bad_exact:
        return False

    low = title.lower()
    bad_contains = [
        "contact form",
        "conditions of use",
        "privacy policy",
        "shipping & returns",
        "wholesale opportunities",
        "results per page",
        "filter by",
    ]
    return not any(item in low for item in bad_contains)


def find_product_container(anchor: Tag) -> Tag | None:
    node: Tag | None = anchor
    for _ in range(9):
        if node is None:
            return None

        text = clean_text(node.get_text(" ", strip=True))
        if "CDN" in text and (
            "Buy Now" in text
            or "more info" in text
            or "Sold Out" in text
            or "In Stock" in text
        ):
            return node

        parent = node.parent
        node = parent if isinstance(parent, Tag) else None

    return None


def extract_products_from_page(soup: BeautifulSoup, expected_aliases: list[str]) -> list[dict[str, str | float]]:
    out: list[dict[str, str | float]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        title = clean_text(a.get_text(" ", strip=True))
        if not is_probable_product_title(title):
            continue

        href = a.get("href", "").strip()
        if not href:
            continue

        product_url = urljoin(BASE_URL, href)
        if product_url in seen:
            continue

        container = find_product_container(a)
        if container is None:
            continue

        container_text = clean_text(container.get_text(" ", strip=True))
        price = parse_price_from_text(container_text)
        if price is None:
            continue

        haystack = f"{title} {container_text}"
        if not any(matches_alias(haystack, alias) for alias in expected_aliases):
            continue

        seen.add(product_url)
        out.append(
            {
                "title": title,
                "price_cad": price,
                "product_url": product_url,
                "detected_knife_type": detect_knife_type_from_title(title),
                "container_text": container_text,
            }
        )

    return out


def dedupe_rows(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, object]] = []

    for row in rows:
        steel_group = str(row.get("steel_group", ""))
        product_url = str(row.get("product_url", ""))
        key = (steel_group, product_url)

        if key in seen:
            continue

        seen.add(key)
        out.append(row)

    return out


def scrape_alias(alias: str, steel_group: str) -> tuple[list[dict[str, object]], str, int, str | None]:
    rows: list[dict[str, object]] = []
    pages_scraped = 0
    referer = f"{BASE_URL}/index.php?main_page=search"

    for page_num in range(1, MAX_PAGES_PER_ALIAS + 1):
        url = build_keyword_search_url(alias, page=page_num)
        print(f"[PAGE] {steel_group} | alias={alias} | page={page_num}")
        soup, fetch_result = soup_from_url(url, referer=referer)

        if fetch_result.blocked:
            return rows, "blocked", pages_scraped, fetch_result.error

        if soup is None:
            return rows, "error", pages_scraped, fetch_result.error

        page_rows = extract_products_from_page(soup, expected_aliases=[alias])

        if not page_rows:
            if page_num == 1:
                return rows, "empty", pages_scraped, None
            return rows, "success", pages_scraped, None

        for row in page_rows:
            row["steel_group"] = steel_group
            row["matched_alias"] = alias

        rows.extend(page_rows)
        pages_scraped += 1

    return rows, "success", pages_scraped, f"max_pages reached ({MAX_PAGES_PER_ALIAS})"


def scrape_steel_group(steel_group: str, aliases: list[str]) -> tuple[list[dict[str, object]], ListingStatus]:
    all_rows: list[dict[str, object]] = []
    any_success = False
    last_message: str | None = None
    total_pages = 0

    for idx, alias in enumerate(aliases, start=1):
        print(f"[ALIAS] {steel_group} | trying {idx}/{len(aliases)}: {alias}")
        alias_rows, status, pages_scraped, message = scrape_alias(alias, steel_group)
        total_pages += pages_scraped
        last_message = message

        if alias_rows:
            any_success = True
            all_rows.extend(alias_rows)

        if status == "blocked":
            deduped = dedupe_rows(all_rows)
            return deduped, ListingStatus(
                steel_group=steel_group,
                status="partial_blocked" if deduped else "blocked",
                pages_scraped=total_pages,
                product_count=len(deduped),
                message=message,
            )

        if idx < len(aliases):
            sleep_range(BETWEEN_ALIASES_DELAY_RANGE, f"between aliases for {steel_group}")
            reset_session()

    all_rows = dedupe_rows(all_rows)

    if any_success:
        return all_rows, ListingStatus(
            steel_group=steel_group,
            status="success",
            pages_scraped=total_pages,
            product_count=len(all_rows),
            message=last_message,
        )

    return [], ListingStatus(
        steel_group=steel_group,
        status="empty",
        pages_scraped=total_pages,
        product_count=0,
        message=last_message or "no results found for any alias",
    )


def remove_high_outliers(series: pd.Series, max_fraction_to_trim: float = 0.1) -> pd.Series:
    if series.empty or len(series) <= 1:
        return series
    k = max(1, int(round(len(series) * max_fraction_to_trim)))
    return series.sort_values().reset_index(drop=True).iloc[:-k]


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    usable = df[df["knife_type"].isin(["folding", "fixed"])].copy()
    grouped = (
        usable.groupby(["steel_group", "knife_type"])["price_cad"]
        .apply(lambda s: remove_high_outliers(s).mean())
        .reset_index(name="mean_price_cad")
    )

    wide = grouped.pivot(index="steel_group", columns="knife_type", values="mean_price_cad").reset_index()
    wide.columns.name = None

    for col in ["folding", "fixed"]:
        if col not in wide.columns:
            wide[col] = pd.NA

    return wide[["steel_group", "folding", "fixed"]].sort_values("steel_group").reset_index(drop=True)


def save_progress(
    all_rows: list[dict[str, object]],
    unresolved: list[str],
    status_rows: list[dict[str, object]],
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
                    "product_url",
                ]
            )
            .copy()
        )

        raw_df = raw_df[
            [
                "steel_group",
                "matched_alias",
                "knife_type",
                "price_cad",
                "title",
                "product_url",
            ]
        ].sort_values(
            [
                "steel_group",
                "knife_type",
                "price_cad",
                "title",
            ]
        ).reset_index(drop=True)

        sheets[SHEET_RAW] = raw_df
        sheets[SHEET_SUMMARY] = build_summary(raw_df)

    write_price_sheets(sheets)

def load_resume_state() -> tuple[
    list[dict[str, object]],
    list[str],
    list[dict[str, object]],
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
        "count_known_type",
    }.issubset(status_df.columns):
        success_mask = (
            pd.to_numeric(
                status_df["count_known_type"],
                errors="coerce",
            )
            .fillna(0)
            .gt(0)
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
    all_rows, unresolved, status_rows, already_done = load_resume_state()
    groups_to_process = list(STEEL_GROUPS.keys())
    remaining = [group for group in groups_to_process if group not in already_done]

    print(f"[INFO] Number of steel groups total : {len(groups_to_process)}")
    print(f"[INFO] Already processed groups    : {len(already_done)}")
    print(f"[INFO] Remaining groups            : {len(remaining)}")

    for idx, steel_group in enumerate(remaining, start=1):
        print(f"\n=== {steel_group} ({idx}/{len(remaining)}) ===")
        aliases = STEEL_GROUPS[steel_group]

        try:
            steel_rows, listing_status = scrape_steel_group(steel_group, aliases)

            for row in steel_rows:
                detected_type = str(row.get("detected_knife_type", "unknown"))
                row["knife_type"] = detected_type

            known_rows = [row for row in steel_rows if row.get("knife_type") in {"fixed", "folding"}]
            unknown_rows = [row for row in steel_rows if row.get("knife_type") == "unknown"]

            if known_rows:
                all_rows.extend(known_rows)

            status_rows.append(
                {
                    "steel_group": steel_group,
                    "status": listing_status.status,
                    "count_all": len(steel_rows),
                    "count_known_type": len(known_rows),
                    "count_unknown_type": len(unknown_rows),
                    "pages_scraped": listing_status.pages_scraped,
                    "message": listing_status.message,
                }
            )

            if not known_rows:
                unresolved.append(steel_group)
                print(f"[WARN] unresolved: {steel_group} ({listing_status.status})")
            else:
                unresolved = [
                    group
                    for group in unresolved
                    if group != steel_group
                ]

                print(
                    f"[OK] processed: {steel_group} | "
                    f"known={len(known_rows)} | unknown={len(unknown_rows)}"
                )

            save_progress(all_rows, unresolved, status_rows)
            sleep_range(BETWEEN_STEELS_DELAY_RANGE, f"between steel groups after {steel_group}")
            reset_session()

        except (requests.RequestException, OSError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            print(f"[ERROR GROUP] {steel_group} -> {exc}")
            unresolved.append(steel_group)
            status_rows.append(
                {
                    "steel_group": steel_group,
                    "status": "error",
                    "count_all": 0,
                    "count_known_type": 0,
                    "count_unknown_type": 0,
                    "pages_scraped": 0,
                    "message": str(exc),
                }
            )
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