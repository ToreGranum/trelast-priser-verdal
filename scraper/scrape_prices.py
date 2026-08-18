import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

OUT = Path("data/prices.json")

STORES = {
    "OBS BYGG Verdal": {
        "city": "Verdal",
        "categories": {
            "ubh": "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/ubehandlet-rekker-og-lekter",
            "imp": "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/impregnert-rekker-og-lekter",
            "grunnet": "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/utvendig-kledning",
        },
    },
    "Bygger'n Verdal": {
        "city": "Verdal",
        "categories": {
            "ubh": "https://www.byggern.no/produkter/trelast/konstruksjonsvirke/konstruksjonsvirke/rekke-lekt-furu-gran",
            "imp": "https://www.byggern.no/produkter/trelast/konstruksjonsvirke/konstruksjonsvirke/rekke-lekt-cu-imp",
            "grunnet": "https://www.byggern.no/produkter/trelast/utvendig-kledning",
        },
    },
    "XL-BYGG Skogn": {
        "city": "Skogn",
        "categories": {
            "ubh": "https://www.xl-bygg.no/category/trelast-og-byggevarer/trelast/rekker-og-lekter",
            "imp": "https://www.xl-bygg.no/category/trelast-og-byggevarer/trelast/rekker-og-lekter",
            "grunnet": "https://www.xl-bygg.no/category/trelast-og-byggevarer/trelast/utvendig-kledning",
        },
    },
}

TARGETS = {
    "ubh": ["48x98", "48x148", "48x198", "23x048", "30x048", "36x048"],
    "imp": ["48x98", "48x148", "48x198", "23x048", "30x048", "36x048"],
    "grunnet": ["16x098", "19x098", "19x148", "22x173", "22x198"],
}

# Keep these known-good product pages as fallbacks. Discovery below adds
# products for the complete target list and is preferred when available.
KNOWN_PRODUCTS = [
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/ubehandlet-konstruksjonsvirke/3019536", "48x98", "ubh"),
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/impregnert-konstruksjonsvirke-----0-2514104-2291725/3003426", "48x98", "imp"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54313798", "48x98", "ubh"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54295178", "48x98", "imp"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/bergene-holm-gran-48x098x4800-k-virke-c24-500423674", "48x98", "ubh"),
]


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", s.lower())


def dimension_matches(text: str, dimension: str) -> bool:
    n = norm(text)
    a, b = dimension.lower().split("x")
    return f"{a}x{b}" in n or f"{a}x0{b}" in n or f"{a}x{int(b):03d}" in n


def parse_price(text: str):
    # Only accept prices explicitly expressed per metre. This prevents a
    # pack/stykk price from being mistaken for a metre price.
    patterns = [
        r"(?:kr\s*)?(\d{1,5}(?:[ .]\d{3})*[,.]\d{2})\s*(?:per|/|pr\.?)\s*m\b",
        r"(?:kr\s*)?(\d{1,5}[,.]\d{2})\s*m\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = match.group(1).replace(" ", "").replace(".", "").replace(",", ".")
            return float(value)
    return None


def choose_store(page, store_name: str) -> bool:
    wanted = STORES[store_name]["city"]
    full_name = store_name.lower()

    # First try the common store picker.
    selectors = [
        "text=Velg butikk", "text=Velg varehus",
        "button:has-text('Velg butikk')", "button:has-text('Velg varehus')",
        "[aria-label*='butikk' i]", "[aria-label*='varehus' i]",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1200):
                loc.click(timeout=2000)
                page.wait_for_timeout(500)
                break
        except Exception:
            pass

    for selector in ["input[placeholder*='Søk' i]", "input[placeholder*='butikk' i]", "input[type='search']"]:
        try:
            inp = page.locator(selector).first
            if inp.is_visible(timeout=1000):
                inp.fill(wanted)
                page.wait_for_timeout(800)
                candidates = page.get_by_text(wanted, exact=False)
                if candidates.count():
                    candidates.first.click(timeout=2500)
                    page.wait_for_timeout(800)
                    break
        except Exception:
            pass

    text = page.locator("body").inner_text(timeout=8000).lower()
    # Store-specific pages often expose either the full store name or the
    # city after selection. We require the requested city to be present and
    # reject pages that still explicitly ask the visitor to choose a store.
    return wanted.lower() in text and "velg butikk" not in text[:4000] and "velg varehus" not in text[:4000]


def discover_links(page, category_url: str, dimension: str, kind: str):
    try:
        page.goto(category_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1200)
        for _ in range(4):
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(600)
    except Exception as exc:
        print(f"WARN category {category_url}: {exc}")
        return []

    links = []
    for anchor in page.locator("a[href]").all():
        try:
            href = anchor.get_attribute("href") or ""
            text = anchor.inner_text(timeout=500)
            combined = f"{text} {href}"
            if not dimension_matches(combined, dimension):
                continue
            low = combined.lower()
            if kind == "imp" and not any(x in low for x in ("imp", "cuimp", "cu-imp")):
                continue
            if kind == "grunnet" and not any(x in low for x in ("grun", "bas")):
                continue
            absolute = urljoin(category_url, href)
            if absolute.startswith("http") and absolute not in links:
                links.append(absolute)
        except Exception:
            continue
    return links[:5]


def scrape_product(page, store_name, url, dimension, kind):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1000)
    verified = choose_store(page, store_name)
    if not verified:
        return None
    text = page.locator("body").inner_text(timeout=10000)
    if not dimension_matches(text[:12000], dimension):
        return None
    price = parse_price(text)
    return price


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"items": []}
    old_map = {(x["store"], x["dimension"], x["type"]): x for x in old.get("items", [])}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="nb-NO")
        page = context.new_page()

        for store_name, config in STORES.items():
            for kind, dimensions in TARGETS.items():
                for dimension in dimensions:
                    key = (store_name, dimension, kind)
                    previous = old_map.get(key, {})

                    urls = [u for s, u, d, k in KNOWN_PRODUCTS if s == store_name and d == dimension and k == kind]
                    if not urls:
                        urls = discover_links(page, config["categories"][kind], dimension, kind)

                    price = None
                    for url in urls:
                        try:
                            price = scrape_product(page, store_name, url, dimension, kind)
                            if price is not None:
                                print(f"OK {store_name} {dimension} {kind}: {price}")
                                break
                        except Exception as exc:
                            print(f"WARN {store_name} {dimension} {kind}: {exc}")

                    if price is not None:
                        old_map[key] = {
                            "store": store_name,
                            "dimension": dimension,
                            "type": kind,
                            "price_per_meter": price,
                            "verified_local": True,
                            "status": "Lokalpris bekreftet",
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        }
                    elif previous.get("price_per_meter") is not None and previous.get("verified_local"):
                        old_map[key] = {
                            **previous,
                            "status": "Siste bekreftede lokalpris – ny sjekk feilet",
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        }
                    else:
                        # Never invent a price. The website will show no price
                        # until the store-specific scraper has confirmed one.
                        old_map[key] = {
                            "store": store_name,
                            "dimension": dimension,
                            "type": kind,
                            "price_per_meter": None,
                            "verified_local": False,
                            "status": "Ingen bekreftet lokalpris",
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        }

        context.close()
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"updated_at": datetime.now(timezone.utc).isoformat(), "items": list(old_map.values())},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
