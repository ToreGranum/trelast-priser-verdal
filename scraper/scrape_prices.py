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
        "aliases": ["XL-BYGG Skogn", "XL-BYGG Gunnar T. Strøm avd. Skogn", "Skogn"],
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
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/moelven-gran-48x098-k-virke-c24-500357616", "48x98", "ubh"),
]


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", s.lower())


def dimension_matches(text: str, dimension: str) -> bool:
    n = norm(text)
    a, b = dimension.lower().split("x")
    b_int = str(int(b))
    return any(norm(f"{a}x{candidate}") in n for candidate in {b, b_int, b_int.zfill(3)})


def _number(value):
    try:
        return float(str(value).replace(" ", "").replace(".", "").replace(",", "."))
    except (TypeError, ValueError):
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None


def parse_product_price(text: str):
    """Hent prisen slik butikken faktisk oppgir den på produktsiden.

    Vi konverterer ikke til pris/m. Et produkt kan derfor bli lagret som stk,
    m, pakke osv. Poenget er å bruke konkret produktpris og original enhet.
    """
    cleaned = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()

    # JSON-LD er ofte den mest stabile kilden på moderne nettbutikker.
    # Vi bruker bare tilbud som faktisk finnes på produktsiden.
    # Hvis samme pris tydelig står med /m, beholdes m som original enhet.
    # Playwright legger script-innhold i body-text på enkelte sider, så dette
    # fungerer også som tekstfallback.
    patterns = [
        (r"(?:kr\s*)?(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:kr\s*)?(?:/\s*)?(stk|stykk|enhet|pakke|pk|m|meter|lm|løpemeter)\b", 1),
        (r"(?:pris|salgspris|nettpris)[^0-9]{0,40}(?:kr\s*)?(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:kr)?", 1),
    ]

    # Foretrekk eksplisitt enhet.
    for pattern, _ in patterns[:1]:
        for match in re.finditer(pattern, cleaned, flags=re.I):
            price = _number(match.group(1))
            unit = match.group(2).lower()
            if price is None or price <= 0:
                continue
            if unit in {"stk", "stykk", "enhet"}:
                unit = "stk"
            elif unit in {"pk", "pakke"}:
                unit = "pakke"
            elif unit in {"lm", "løpemeter"}:
                unit = "m"
            return price, unit

    # Vanlige produktsider viser bare f.eks. "41,90" ved siden av kjøpsfeltet.
    # Bruk et kort pris-kontekstområde, men ta med eventuell original enhet.
    for label in ("salgspris", "nettpris", "pris"):
        for match in re.finditer(label, cleaned, flags=re.I):
            context = cleaned[match.start():match.start() + 180]
            price_match = re.search(r"(?:kr\s*)?(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:kr)?", context, flags=re.I)
            if not price_match:
                continue
            price = _number(price_match.group(1))
            if price is None or price <= 0:
                continue
            unit_match = re.search(r"(?:/|per|pr\.?)\s*(stk|stykk|enhet|pakke|pk|m|meter|lm|løpemeter)\b", context, flags=re.I)
            unit = unit_match.group(1).lower() if unit_match else "stk"
            if unit in {"stk", "stykk", "enhet"}:
                unit = "stk"
            elif unit in {"pk", "pakke"}:
                unit = "pakke"
            else:
                unit = "m"
            return price, unit

    # Sist: et tydelig norsk prisbeløp i den øvre delen av produktsiden.
    # Dette er kun fallback for butikker som ikke bruker prisetikett.
    head = cleaned[:6000]
    for match in re.finditer(r"(?:kr\s*)?(\d{1,5}[.,]\d{2})\b", head):
        price = _number(match.group(1))
        if price is None or price <= 0 or price > 100000:
            continue
        around = head[max(0, match.start()-40):match.end()+60]
        if re.search(r"(?:art\.?\s*nr|postnr|telefon|nummer)\s*$", around, re.I):
            continue
        unit_match = re.search(r"(?:/|per|pr\.?)\s*(stk|stykk|enhet|pakke|pk|m|meter|lm|løpemeter)\b", around, re.I)
        unit = "stk" if not unit_match else unit_match.group(1).lower()
        if unit in {"stykk", "enhet"}:
            unit = "stk"
        elif unit in {"pk", "pakke"}:
            unit = "pakke"
        elif unit in {"lm", "løpemeter", "meter"}:
            unit = "m"
        return price, unit

    return None, None


def visible_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def click_store_picker(page):
    patterns = [re.compile(r"^\s*Velg butikk\s*$", re.I), re.compile(r"^\s*Velg varehus\s*$", re.I)]
    for pattern in patterns:
        for locator in [page.get_by_role("button", name=pattern), page.get_by_role("link", name=pattern), page.get_by_text(pattern)]:
            try:
                for i in range(min(locator.count(), 8)):
                    item = locator.nth(i)
                    if item.is_visible(timeout=500):
                        item.click(timeout=3000)
                        page.wait_for_timeout(900)
                        return True
            except Exception:
                pass
    return False


def choose_store(page, store_name: str) -> bool:
    config = STORES[store_name]
    city = config["city"]
    aliases = config.get("aliases", [store_name, city])
    click_store_picker(page)

    for selector in ["input[placeholder*='Søk' i]", "input[placeholder*='butikk' i]", "input[placeholder*='varehus' i]", "input[type='search']"]:
        try:
            inputs = page.locator(selector)
            for i in range(min(inputs.count(), 5)):
                inp = inputs.nth(i)
                if inp.is_visible(timeout=500):
                    inp.fill(city)
                    page.wait_for_timeout(1200)
                    break
        except Exception:
            pass

    for name in aliases + [store_name, city]:
        try:
            exact = page.get_by_text(name, exact=True)
            for i in range(min(exact.count(), 10)):
                item = exact.nth(i)
                if item.is_visible(timeout=500):
                    item.click(timeout=3000)
                    page.wait_for_timeout(1800)
                    return True
        except Exception:
            pass

    for name in aliases:
        try:
            loc = page.get_by_role("button", name=re.compile(re.escape(name), re.I))
            for i in range(min(loc.count(), 8)):
                item = loc.nth(i)
                if item.is_visible(timeout=500):
                    item.click(timeout=3000)
                    page.wait_for_timeout(1800)
                    return True
        except Exception:
            pass

    # Produktprisen kan være offentlig selv om butikkvelgeren ikke åpnet.
    # Ikke stopp hele scrapingjobben bare fordi butikkvelgeren feiler.
    print(f"STORE SELECT NOT CONFIRMED {store_name}")
    return False


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
    selected = choose_store(page, store_name)
    page.wait_for_timeout(1200)
    text = visible_text(page)
    if not dimension_matches(text[:18000], dimension):
        print(f"NO DIMENSION {dimension}: {url}")
        return None, None, selected
    price, unit = parse_product_price(text)
    if price is None:
        print(f"NO PRODUCT PRICE {store_name} {dimension}: {url}")
    return price, unit, selected


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
                    urls = [u for s, u, d, k in KNOWN_PRODUCTS if s == store_name and d == dimension and k == kind]
                    if not urls:
                        urls = discover_links(page, config["categories"][kind], dimension, kind)

                    price = None
                    unit = None
                    selected = False
                    for url in urls:
                        try:
                            price, unit, selected = scrape_product(page, store_name, url, dimension, kind)
                            if price is not None:
                                print(f"OK {store_name} {dimension} {kind}: {price:.2f} / {unit}")
                                break
                        except Exception as exc:
                            print(f"WARN {store_name} {dimension} {kind}: {exc}")

                    if price is not None:
                        old_map[key] = {
                            "store": store_name,
                            "dimension": dimension,
                            "type": kind,
                            "price_per_unit": price,
                            "unit": unit or "stk",
                            "verified_local": bool(selected),
                            "status": "Konkret produktpris bekreftet" + (" lokalt" if selected else " på produktsiden"),
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        }
                    elif key not in old_map or old_map[key].get("price_per_unit") is None:
                        old_map[key] = {
                            "store": store_name,
                            "dimension": dimension,
                            "type": kind,
                            "price_per_unit": None,
                            "unit": "stk",
                            "verified_local": False,
                            "status": "Ingen bekreftet produktpris",
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                        }
                    else:
                        # Ikke slett siste kjente pris bare fordi en butikk midlertidig
                        # blokkerer eller endrer nettsiden.
                        old_map[key]["status"] = "Sist kjente produktpris – ny kontroll feilet"
                        old_map[key]["checked_at"] = datetime.now(timezone.utc).isoformat()

        context.close()
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "items": list(old_map.values())}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
