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
        "aliases": ["OBS BYGG Verdal", "Verdal"],
        "categories": {
            "ubh": "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/ubehandlet-rekker-og-lekter",
            "imp": "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/impregnert-rekker-og-lekter",
            "grunnet": "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/utvendig-kledning",
        },
    },
    "Bygger'n Verdal": {
        "city": "Verdal",
        "aliases": ["Bygger'n Verdal", "Bygger'n", "Verdal"],
        "categories": {
            "ubh": "https://www.byggern.no/produkter/trelast/konstruksjonsvirke/konstruksjonsvirke/rekke-lekt-furu-gran",
            "imp": "https://www.byggern.no/produkter/trelast/konstruksjonsvirke/konstruksjonsvirke/rekke-lekt-cu-imp",
            "grunnet": "https://www.byggern.no/produkter/trelast/utvendig-kledning",
        },
    },
    "XL-BYGG Skogn": {
        "city": "Skogn",
        "aliases": ["XL-BYGG Skogn", "Skogn"],
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

KNOWN_PRODUCTS = [
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/ubehandlet-konstruksjonsvirke/3019536", "48x98", "ubh"),
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/impregnert-konstruksjonsvirke-----0-2514104-2291725/3003426", "48x98", "imp"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54313798", "48x98", "ubh"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54230960", "48x98", "imp"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/bergene-holm-gran-48x098x4800-k-virke-c24-500423674", "48x98", "ubh"),
]


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", s.lower())


def dimension_matches(text: str, dimension: str) -> bool:
    n = norm(text)
    a, b = dimension.lower().split("x")
    b_int = str(int(b))
    return any(f"{a}x{candidate}" in n for candidate in {b, b_int, b_int.zfill(3)})


def parse_price(text: str):
    """Find a price explicitly expressed per running metre.

    The retailers often render a Norwegian price as separate DOM nodes, e.g.
    `33` `95` `per m`, which becomes `33 95 per m` in inner_text().
    """
    cleaned = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()
    patterns = [
        # 33 95 per m / 33 95 / m
        r"(?:kr\s*)?(\d{1,5})\s+(\d{2})\s*(?:per\s*m|/\s*m|pr\.?\s*m)\b",
        # 33,95 per m / 33.95 per m
        r"(?:kr\s*)?(\d{1,5}(?:[.,]\d{2}))\s*(?:per\s*m|/\s*m|pr\.?\s*m)\b",
        # 33 95 kr per meter / 33,95 kr per meter
        r"(?:kr\s*)?(\d{1,5})\s+(\d{2})\s*(?:kr\s*)?(?:per\s*)?meter\b",
        r"(?:kr\s*)?(\d{1,5}(?:[.,]\d{2}))\s*(?:kr\s*)?(?:per\s*)?meter\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.I)
        if not match:
            continue
        if len(match.groups()) == 2 and match.group(2).isdigit():
            value = f"{match.group(1)}.{match.group(2)}"
        else:
            value = match.group(1).replace(" ", "").replace(",", ".")
        try:
            return float(value)
        except ValueError:
            pass
    return None


def visible_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def click_store_picker(page):
    # Retailers use slightly different markup. Try visible buttons/links first.
    patterns = [
        re.compile(r"^\s*Velg butikk\s*$", re.I),
        re.compile(r"^\s*Velg varehus\s*$", re.I),
        re.compile(r"butikk", re.I),
        re.compile(r"varehus", re.I),
    ]
    for pattern in patterns:
        for locator in [page.get_by_role("button", name=pattern), page.get_by_role("link", name=pattern)]:
            try:
                for i in range(min(locator.count(), 4)):
                    item = locator.nth(i)
                    if item.is_visible(timeout=500):
                        item.click(timeout=2500)
                        page.wait_for_timeout(800)
                        return True
            except Exception:
                pass
    return False


def choose_store(page, store_name: str) -> bool:
    city = STORES[store_name]["city"]
    click_store_picker(page)

    # Search fields in the store dialog/header.
    search_selectors = [
        "input[placeholder*='Søk' i]",
        "input[placeholder*='butikk' i]",
        "input[placeholder*='varehus' i]",
        "input[type='search']",
    ]
    for selector in search_selectors:
        try:
            inputs = page.locator(selector)
            for i in range(min(inputs.count(), 3)):
                inp = inputs.nth(i)
                if inp.is_visible(timeout=500):
                    inp.fill(city)
                    page.wait_for_timeout(1000)
                    break
        except Exception:
            pass

    # Click the city/store result. Exact city matching avoids accidentally
    # selecting Levanger/Steinkjer/etc. when Verdal is requested.
    for name in [store_name, city]:
        try:
            loc = page.get_by_text(name, exact=True)
            for i in range(min(loc.count(), 6)):
                item = loc.nth(i)
                if item.is_visible(timeout=500):
                    item.click(timeout=2500)
                    page.wait_for_timeout(1200)
                    break
        except Exception:
            pass

    # Some dialogs render the store name as part of a card instead of exact text.
    if city.lower() not in visible_text(page).lower():
        return False

    # Give the site time to update its selected-store state and price.
    page.wait_for_timeout(1200)
    text = visible_text(page)
    low = text.lower()
    # A remaining generic picker prompt means we did not actually select it.
    prompts = low.count("velg butikk") + low.count("velg varehus")
    return city.lower() in low and prompts < 2


def discover_links(page, category_url: str, dimension: str, kind: str):
    try:
        page.goto(category_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1800)
        for _ in range(6):
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(700)
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
            if kind == "imp" and not any(x in low for x in ("imp", "cuimp", "cu-imp", "ntr")):
                continue
            if kind == "grunnet" and not any(x in low for x in ("grun", "grunn", "malt")):
                continue
            absolute = urljoin(category_url, href)
            if absolute.startswith("http") and absolute not in links:
                links.append(absolute)
        except Exception:
            continue
    return links[:8]


def scrape_product(page, store_name, url, dimension, kind):
    print(f"CHECK {store_name} {dimension} {kind} {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1400)
    if not choose_store(page, store_name):
        print(f"NO STORE {store_name}: {url}")
        return None
    text = visible_text(page)
    if not dimension_matches(text[:18000], dimension):
        print(f"NO DIMENSION {dimension}: {url}")
        return None
    price = parse_price(text)
    if price is None:
        print(f"NO PRICE {store_name} {dimension}: {url}")
    return price


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"items": []}
    old_map = {(x["store"], x["dimension"], x["type"]): x for x in old.get("items", [])}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="nb-NO", timezone_id="Europe/Oslo")
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
                                print(f"OK {store_name} {dimension} {kind}: {price:.2f}")
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
