from __future__ import annotations

import json
import math
import random
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

CATEGORY_SOURCES: list[dict[str, str]] = [
    {"source_name": "pocket", "knife_type": "folding", "url": "https://www.bladehq.com/cat--Pocket-Knives--45"},
    {"source_name": "automatic", "knife_type": "folding", "url": "https://www.bladehq.com/cat--Automatic-Knives--40"},
    {"source_name": "otf", "knife_type": "folding", "url": "https://www.bladehq.com/cat--Out-The-Front-Automatics--41"},
    {"source_name": "spring_assisted", "knife_type": "folding", "url": "https://www.bladehq.com/cat--Spring-Assisted-Knives--46"},
    {"source_name": "butterfly", "knife_type": "folding", "url": "https://www.bladehq.com/cat--Butterfly-Knives--70"},
    {"source_name": "fixed", "knife_type": "fixed", "url": "https://www.bladehq.com/cat--Fixed-Blade-Knives--179"},
    {"source_name": "kitchen", "knife_type": "fixed", "url": "https://www.bladehq.com/cat--Kitchen-Knives--256"},
]

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
    "CTS-XHP": ["CTS-XHP", "XHP"],
    "D2": ["D2"],
    "Elmax": ["Elmax"],
    "H1": ["H1"],
    "K390": ["K390"],
    "LC200N": ["LC200N"],
    "M2": ["M2"],
    "M390 / PM-20CV / CTS-204P": ["M390", "20CV", "CPM-20CV", "CPM 20CV", "204P", "CTS-204P"],
    "M398": ["M398"],
    "Maxamet": ["Maxamet"],
    "N690": ["N690"],
    "Nitro-V": ["Nitro-V"],
    "O1": ["O1"],
    "PM-10V": ["10V", "CPM-10V", "CPM 10V"],
    "PM-154": ["CPM-154", "CPM 154"],
    "PM-3V": ["3V", "CPM-3V", "CPM 3V"],
    "PM-4V": ["4V", "CPM-4V", "CPM 4V"],
    "PM-CruWear": ["CRU-WEAR", "Cru-Wear", "CPM-CruWear", "CPM CruWear"],
    "PM-M4": ["M4", "CPM-M4", "CPM M4"],
    "PM-MagnaCut": ["MagnaCut", "CPM-MagnaCut", "CPM MagnaCut"],
    "PM-S110V": ["S110V", "CPM-S110V", "CPM S110V"],
    "PM-S125V": ["S125V", "CPM-S125V", "CPM S125V"],
    "PM-S30V": ["S30V", "CPM-S30V", "CPM S30V"],
    "PM-S35VN": ["S35VN", "CPM-S35VN", "CPM S35VN"],
    "PM-S45VN": ["S45VN", "CPM-S45VN", "CPM S45VN"],
    "PM-S60V": ["S60V", "CPM-S60V", "CPM S60V"],
    "PM-S90V": ["S90V", "CPM-S90V", "CPM S90V"],
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

BASE_DIR = Path(__file__).resolve().parent

PRICE_WORKBOOK = BASE_DIR / "steel_price_data.xlsx"

SHEET_RAW = "BHQ_Raw"
SHEET_SUMMARY = "BHQ_Summary"
SHEET_UNMATCHED = "BHQ_Unmatched"

CHECKPOINT_JSON = BASE_DIR / "bladehq_checkpoint.json"
CACHE_DIR = BASE_DIR / "bladehq_cache"
CACHE_DIR.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

PRE_PAGE_DELAY = (0.8, 1.6)
POST_PAGE_DELAY = (0.7, 1.4)
PRE_DETAIL_DELAY = (0.4, 0.9)
POST_DETAIL_DELAY = (0.3, 0.7)
DEFAULT_TIMEOUT_MS = 45_000
DEFAULT_LISTING_PAGE_SIZE = 24
MAX_DETAIL_PAGES: int | None = None
VISIT_ALL_PRODUCT_PAGES = False

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

def clean_text(text: str) -> str:
    return " ".join(text.split()).strip()


def sleep_range(bounds: tuple[float, float]) -> None:
    time.sleep(random.uniform(*bounds))


def parse_price(text: str) -> float | None:
    prices = re.findall(r"\$([0-9][0-9,]*(?:\.\d{2})?)", text)
    if not prices:
        return None
    return float(prices[-1].replace(",", ""))


def build_alias_patterns() -> list[tuple[str, re.Pattern[str], str]]:
    patterns: list[tuple[str, re.Pattern[str], str]] = []
    for steel_group, aliases in STEEL_GROUPS.items():
        for alias in aliases:
            escaped = re.escape(alias)
            patterns.append((steel_group, re.compile(rf"(?<![A-Z0-9]){escaped}(?![A-Z0-9])", re.IGNORECASE), alias))
    patterns.sort(key=lambda x: len(x[2]), reverse=True)
    return patterns


ALIAS_PATTERNS = build_alias_patterns()


def detect_steel_group(text: str) -> tuple[str | None, str | None]:
    text = clean_text(text)
    for steel_group, pattern, alias in ALIAS_PATTERNS:
        if pattern.search(text):
            return steel_group, alias
    return None, None


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, set):
        return sorted(_jsonable(v) for v in obj)
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _restore_checkpoint_types(data: dict[str, Any]) -> dict[str, Any]:
    listing_products = data.get("listing_products", {})
    restored: dict[str, Any] = {}
    for url, entry in listing_products.items():
        restored[url] = {
            **entry,
            "knife_types": set(entry.get("knife_types", [])),
            "sources": set(entry.get("sources", [])),
        }
    data["listing_products"] = restored
    if "detail_done" not in data or not isinstance(data["detail_done"], dict):
        data["detail_done"] = {}
    return data


def checkpoint_load() -> dict[str, Any]:
    if CHECKPOINT_JSON.exists():
        try:
            data = json.loads(CHECKPOINT_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _restore_checkpoint_types(data)
        except Exception:
            pass
    return {"listing_products": {}, "detail_done": {}}


def checkpoint_save(data: dict[str, Any]) -> None:
    CHECKPOINT_JSON.write_text(json.dumps(_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")


def extract_total_pages(page) -> int:
    body_text = page.locator("body").inner_text(timeout=DEFAULT_TIMEOUT_MS)
    m = re.search(r"Showing\s+\d+\s*-\s*\d+\s+of\s+([0-9,]+)\s+items", body_text, re.I)
    if not m:
        return 1
    total_items = int(m.group(1).replace(",", ""))
    return max(1, math.ceil(total_items / DEFAULT_LISTING_PAGE_SIZE))


def extract_card_payload(page) -> list[dict[str, Any]]:
    js = r"""
    () => {
      const out = [];
      const seen = new Set();
      const titleNodes = Array.from(document.querySelectorAll('h2'));
      function textOf(node) {
        return (node && node.innerText ? node.innerText : '').replace(/\s+/g, ' ').trim();
      }
      function bestCard(node) {
        let cur = node;
        for (let i = 0; i < 10 && cur; i += 1) {
          const txt = textOf(cur);
          if (/Our (Sale )?Price:/i.test(txt) || /Email or Call for Price/i.test(txt)) return cur;
          cur = cur.parentElement;
        }
        return null;
      }
      for (const h2 of titleNodes) {
        const title = textOf(h2);
        if (!title) continue;
        const card = bestCard(h2);
        if (!card) continue;
        const cardText = textOf(card);
        const key = title + ' || ' + cardText;
        if (seen.has(key)) continue;
        seen.add(key);
        let href = null;
        const links = Array.from(card.querySelectorAll('a[href]'));
        for (const a of links) {
          const candidate = a.getAttribute('href') || '';
          if (candidate.includes('/item--')) {
            href = a.href;
            break;
          }
        }
        out.push({title, card_text: cardText, product_url: href});
      }
      return out;
    }
    """
    return page.evaluate(js)


def extract_listing_rows(page, source_name: str, knife_type: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in extract_card_payload(page):
        title = clean_text(item.get("title") or "")
        if not title:
            continue
        if title.lower() in {"brand", "feature", "use", "style", "type", "featured", "pocket knives", "fixed blade knives", "automatic knives", "out the front knives", "butterfly knives", "kitchen knives", "spring assisted knives", "knives"}:
            continue
        card_text = clean_text(item.get("card_text") or "")
        price = None
        m_sale = re.search(r"Our Sale Price:\s*\$([0-9][0-9,]*(?:\.\d{2})?)", card_text, re.I)
        if m_sale:
            price = float(m_sale.group(1).replace(",", ""))
        else:
            m_regular = re.search(r"Our Price:\s*\$([0-9][0-9,]*(?:\.\d{2})?)", card_text, re.I)
            if m_regular:
                price = float(m_regular.group(1).replace(",", ""))
            else:
                price = parse_price(card_text)
        if price is None:
            continue
        product_url = item.get("product_url")
        if not product_url:
            continue
        steel_group, matched_alias = detect_steel_group(title)
        out.append({
            "product_url": product_url,
            "title": title,
            "listing_price_usd": price,
            "listing_steel_group": steel_group,
            "listing_matched_alias": matched_alias,
            "source_name": source_name,
            "knife_type": knife_type,
        })
    return out


def merge_listing_product(index: dict[str, Any], row: dict[str, Any]) -> None:
    url = row["product_url"]
    entry = index.setdefault(url, {
        "product_url": url,
        "title": row["title"],
        "listing_prices": [],
        "knife_types": set(),
        "sources": set(),
        "listing_steel_group": row.get("listing_steel_group"),
        "listing_matched_alias": row.get("listing_matched_alias"),
    })
    entry["title"] = entry.get("title") or row["title"]
    entry["listing_prices"].append(row["listing_price_usd"])
    entry["knife_types"].add(row["knife_type"])
    entry["sources"].add(row["source_name"])
    if not entry.get("listing_steel_group") and row.get("listing_steel_group"):
        entry["listing_steel_group"] = row.get("listing_steel_group")
        entry["listing_matched_alias"] = row.get("listing_matched_alias")


def scrape_listings(page, checkpoint: dict[str, Any]) -> dict[str, Any]:
    listing_products: dict[str, Any] = checkpoint.get("listing_products", {})
    for source in CATEGORY_SOURCES:
        source_name = source["source_name"]
        knife_type = source["knife_type"]
        base_url = source["url"]
        print(f"\n=== listing source: {source_name} ===")
        sleep_range(PRE_PAGE_DELAY)
        page.goto(base_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
        page.wait_for_timeout(int(random.uniform(*POST_PAGE_DELAY) * 1000))
        total_pages = extract_total_pages(page)
        print(f"[{source_name}] total_pages detected: {total_pages}")
        for page_num in range(1, total_pages + 1):
            url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
            print(f"[{source_name}] page {page_num}/{total_pages}: {url}")
            sleep_range(PRE_PAGE_DELAY)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
                page.wait_for_timeout(int(random.uniform(*POST_PAGE_DELAY) * 1000))
            except PlaywrightTimeoutError:
                print(f"[{source_name}] timeout on page {page_num}; skipping")
                continue
            rows = extract_listing_rows(page, source_name=source_name, knife_type=knife_type)
            print(f"[{source_name}] cards parsed on page {page_num}: {len(rows)}")
            for row in rows:
                merge_listing_product(listing_products, row)
            checkpoint["listing_products"] = listing_products
            checkpoint_save(checkpoint)
    return checkpoint


def safe_cache_name(url: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", url).strip("_")
    return CACHE_DIR / f"{safe[:180]}.txt"


def extract_product_detail_payload(page) -> dict[str, str]:
    js = r"""
    () => {
      const h1 = (document.querySelector('h1')?.innerText || '').replace(/\s+/g, ' ').trim();
      const main = (document.querySelector('main')?.innerText || document.body.innerText || '').replace(/\s+/g, ' ').trim();
      return {h1, main};
    }
    """
    return page.evaluate(js)


def extract_price_from_detail_text(text: str) -> float | None:
    m_sale = re.search(r"Our Sale Price:\s*\$([0-9][0-9,]*(?:\.\d{2})?)", text, re.I)
    if m_sale:
        return float(m_sale.group(1).replace(",", ""))
    m_regular = re.search(r"Our Price:\s*\$([0-9][0-9,]*(?:\.\d{2})?)", text, re.I)
    if m_regular:
        return float(m_regular.group(1).replace(",", ""))
    return parse_price(text)


def choose_knife_type(knife_types: set[str]) -> str:
    if "fixed" in knife_types:
        return "fixed"
    return "folding"


def scrape_product_details(page, checkpoint: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    listing_products: dict[str, Any] = checkpoint["listing_products"]
    detail_done: dict[str, Any] = checkpoint.get("detail_done", {})
    rows: list[dict[str, Any]] = []
    unmatched_titles: list[str] = []
    urls = sorted(listing_products.keys())
    if MAX_DETAIL_PAGES is not None:
        urls = urls[:MAX_DETAIL_PAGES]
    for idx, url in enumerate(urls, start=1):
        entry = listing_products[url]
        title = entry.get("title") or ""
        listing_steel_group = entry.get("listing_steel_group")
        listing_alias = entry.get("listing_matched_alias")
        knife_type = choose_knife_type(entry.get("knife_types", set()))
        listing_price = min(entry.get("listing_prices", [])) if entry.get("listing_prices") else None
        must_visit = VISIT_ALL_PRODUCT_PAGES or not listing_steel_group
        if url in detail_done:
            detail = detail_done[url]
            steel_group = detail.get("steel_group") or listing_steel_group
            matched_alias = detail.get("matched_alias") or listing_alias
            detail_price = detail.get("detail_price_usd")
            final_price = detail_price if detail_price is not None else listing_price
            if steel_group and final_price is not None:
                rows.append({
                    "steel_group": steel_group,
                    "matched_alias": matched_alias,
                    "knife_type": knife_type,
                    "price_usd": final_price,
                    "title": detail.get("title") or title,
                    "product_url": url,
                    "sources": ", ".join(sorted(entry.get("sources", set()))),
                })
            else:
                unmatched_titles.append(detail.get("title") or title)
            continue
        if not must_visit and listing_steel_group and listing_price is not None:
            rows.append({
                "steel_group": listing_steel_group,
                "matched_alias": listing_alias,
                "knife_type": knife_type,
                "price_usd": listing_price,
                "title": title,
                "product_url": url,
                "sources": ", ".join(sorted(entry.get("sources", set()))),
            })
            detail_done[url] = {
                "title": title,
                "steel_group": listing_steel_group,
                "matched_alias": listing_alias,
                "detail_price_usd": listing_price,
                "visited_detail": False,
            }
            checkpoint["detail_done"] = detail_done
            checkpoint_save(checkpoint)
            continue
        print(f"[detail] {idx}/{len(urls)} {url}")
        sleep_range(PRE_DETAIL_DELAY)
        payload: dict[str, str] = {"h1": title, "main": ""}
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            page.wait_for_timeout(int(random.uniform(*POST_DETAIL_DELAY) * 1000))
            payload = extract_product_detail_payload(page)
            detail_text = clean_text((payload.get("h1") or "") + " " + (payload.get("main") or ""))
        except PlaywrightTimeoutError:
            detail_text = ""
        if detail_text:
            safe_cache_name(url).write_text(detail_text, encoding="utf-8")
        else:
            cache_path = safe_cache_name(url)
            if cache_path.exists():
                detail_text = cache_path.read_text(encoding="utf-8")
        steel_group, matched_alias = detect_steel_group(detail_text)
        detail_price = extract_price_from_detail_text(detail_text) if detail_text else None
        final_price = detail_price if detail_price is not None else listing_price
        final_title = clean_text((payload.get("h1") or title) if detail_text else title)
        detail_done[url] = {
            "title": final_title,
            "steel_group": steel_group,
            "matched_alias": matched_alias,
            "detail_price_usd": final_price,
            "visited_detail": True,
        }
        checkpoint["detail_done"] = detail_done
        checkpoint_save(checkpoint)
        if steel_group and final_price is not None:
            rows.append({
                "steel_group": steel_group,
                "matched_alias": matched_alias,
                "knife_type": knife_type,
                "price_usd": final_price,
                "title": final_title,
                "product_url": url,
                "sources": ", ".join(sorted(entry.get("sources", set()))),
            })
        else:
            unmatched_titles.append(final_title or title)
    return rows, sorted(set(unmatched_titles))


def remove_high_outliers(series: pd.Series, max_fraction_to_trim: float = 0.10) -> pd.Series:
    if series.empty or len(series) <= 1:
        return series
    k = max(1, int(round(len(series) * max_fraction_to_trim)))
    if k >= len(series):
        return series
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


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        url = str(row.get("product_url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(row)
    return out


def main() -> None:
    checkpoint = checkpoint_load()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1440, "height": 2400})
        page = context.new_page()
        checkpoint = scrape_listings(page, checkpoint)
        rows, unmatched_titles = scrape_product_details(page, checkpoint)
        context.close()
        browser.close()
    rows = dedupe_rows(rows)
    unmatched_df = pd.DataFrame(
        {
            "title": sorted(set(unmatched_titles))
        }
    )

    if not rows:
        print("No data collected.")

        write_price_sheets(
            {
                SHEET_UNMATCHED: unmatched_df,
            }
        )
        return

    raw_df = pd.DataFrame(rows)

    raw_df = raw_df[
        [
            "steel_group",
            "matched_alias",
            "knife_type",
            "price_usd",
            "title",
            "product_url",
            "sources",
        ]
    ].sort_values(
        [
            "steel_group",
            "knife_type",
            "price_usd",
            "title",
        ]
    ).reset_index(drop=True)

    summary_df = build_summary(raw_df)

    write_price_sheets(
        {
            SHEET_RAW: raw_df,
            SHEET_SUMMARY: summary_df,
            SHEET_UNMATCHED: unmatched_df,
        }
    )

    print("=" * 60)
    print(
        f"Unique matched products : {len(raw_df)}"
    )
    print(
        f"Price workbook          : "
        f"{PRICE_WORKBOOK.resolve()}"
    )
    print(
        f"Checkpoint              : "
        f"{CHECKPOINT_JSON.resolve()}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
