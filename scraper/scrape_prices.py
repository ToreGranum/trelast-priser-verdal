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
        "aliases": ["XL-BYGG Skogn", "XL-BYGG Gunnar T. Strøm avd. Skogn", "Gunnar T. Strøm", "Skogn"],
        "categories": {
            "ubh": "https://www.xl-bygg.no/category/trelast-og-byggevarer/trelast/konstruksjonsvirke",
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

# XL-BYGG har butikkavhengige priser og produktkategoriene deres er dynamiske.
# Derfor bruker vi konkrete produktsider for alle mål vi vil vise, i stedet for
# å være avhengig av at kategorisiden returnerer riktig produktlenke.
KNOWN_PRODUCTS = [
    # OBS
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/ubehandlet-konstruksjonsvirke/3019536", "48x98", "ubh"),
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/impregnert-konstruksjonsvirke-----0-2514104-2291725/3003426", "48x98", "imp"),
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/utvendig-kledning/2167152", "19x148", "grunnet"),
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/utvendig-kledning/2242753", "22x198", "grunnet"),

    # Bygger'n
    ("Bygger'n Verdal", "https://www.byggern.no/product/54313798", "48x98", "ubh"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54230960", "48x98", "imp"),

    # XL-BYGG ubehandlet
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/moelven-gran-48x098-k-virke-c24-500357616", "48x98", "ubh"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/moelven-gran-48x148-k-virke-c24-500557012", "48x148", "ubh"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/hasas-gran-48x198-k-virke-c24-500501502", "48x198", "ubh"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/moelven-g-f-23x048-lekt-kl1-buntet-54230241", "23x048", "ubh"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/moelven-g-f-30x048-lekt-kl1-500563976", "30x048", "ubh"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/moelven-g-f-36x048-lekt-kl1-500520486", "36x048", "ubh"),

    # XL-BYGG impregnert
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/bergene-holm-furu-48x098-cuimp-k-virke-c24-54186194", "48x98", "imp"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/hasas-furu-48x148-cuimp-k-virke-c24-54173677", "48x148", "imp"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/hasas-furu-48x198-cuimp-k-virke-c24-54173696", "48x198", "imp"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/bergene-holm-g-f-23x048-lekt-kl1-bnt-500442927", "23x048", "imp"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/g3-gausdal-treindustrier-furu-30x048-lekt-kl1-cuimp-500437566", "30x048", "imp"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/moelven-furu-36x048-lekt-kl1-cuimp-500533465", "36x048", "imp"),

    # XL-BYGG grunnet
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/eggedal-sag-gran-16x098-rekt-kled-grunnet-60647936", "16x098", "grunnet"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/eggedal-sag-gran-19x098-rekt-kled-grunnet-60648396", "19x098", "grunnet"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/eggedal-sag-gran-19x148-rekt-kled-grunnet-60648398", "19x148", "grunnet"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/moelven-gran-22x173-rektkled-bas-43236234", "22x173", "grunnet"),
    ("XL-BYGG Skogn", "https://www.xl-bygg.no/product/eggedal-sag-gran-22x198-rekt-kled-grunnet-60648406", "22x198", "grunnet"),
]


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(s).lower())


def dimension_matches(text: str, dimension: str) -> bool:
    n = norm(text)
    a, b = dimension.lower().split("x")
    b_int = str(int(b))
    candidates = {b, b_int, b_int.zfill(3)}
    return any(norm(f"{a}x{candidate}") in n for candidate in candidates)


def number(value):
    s = str(value).replace("\u00a0", " ").strip()
    if re.fullmatch(r"\d{1,6}\s+\d{2}", s):
        whole, cents = s.split()
        return float(f"{whole}.{cents}")
    s = s.replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def unit_name(unit):
    unit = unit.lower()
    if unit in {"stk", "stykk", "enhet"}:
        return "stk"
    if unit in {"pk", "pakke"}:
        return "pakke"
    if unit in {"m", "meter", "lm", "løpemeter"}:
        return "m"
    return unit


def parse_product_price(text: str):
    text = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()
    unit_re = r"(stk|stykk|enhet|pakke|pk|m|meter|lm|løpemeter)"
    value_re = r"(\d{1,6}[.,]\d{2}|\d{1,6}\s+\d{2})"

    patterns = [
        rf"(?:kr\s*)?{value_re}\s*(?:kr\s*)?(?:/\s*|per\s+|pr\.?\s*){unit_re}\b",
        rf"(?:kr\s*)?{value_re}\s*(?:kr\s*)?{unit_re}\b",
        rf"(?:/\s*|per\s+|pr\.?\s*){unit_re}\b[^0-9]{{0,40}}(?:kr\s*)?{value_re}",
    ]
    for index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text, flags=re.I):
            groups = match.groups()
            if index == 2:
                unit, value = groups[0], groups[1]
            else:
                value, unit = groups[0], groups[1]
            price = number(value)
            if price is not None and 0 < price < 100000:
                return price, unit_name(unit)

    # Prisetikett uten eksplisitt enhet. Dette er fortsatt konkret produktpris.
    for label in ("salgspris", "nettpris", "pris"):
        for match in re.finditer(label, text, flags=re.I):
            context = text[match.start():match.start() + 240]
            price_match = re.search(value_re, context)
            if not price_match:
                continue
            price = number(price_match.group(1))
            if price is None or not 0 < price < 100000:
                continue
            unit_match = re.search(r"(?:/\s*|per\s+|pr\.?\s*)" + unit_re + r"\b", context, flags=re.I)
            return price, unit_name(unit_match.group(1)) if unit_match else "stk"

    return None, None


def jsonld_price(page):
    for raw in page.locator('script[type="application/ld+json"]').all_text_contents():
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            offers = obj.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if not isinstance(offers, dict):
                continue
            price = number(offers.get("price"))
            unit = offers.get("priceCurrency")
            if price and price > 0:
                # JSON-LD sier normalt ikke om pris er per meter/stk. Ikke gjett.
                return price, "stk"
    return None, None


def visible_text(page):
    try:
        return page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""


def click_store_picker(page):
    patterns = [
        re.compile(r"^\s*Velg butikk\s*$", re.I),
        re.compile(r"^\s*Velg varehus\s*$", re.I),
        re.compile(r"Velg varehus", re.I),
        re.compile(r"Velg butikk", re.I),
    ]
    for pattern in patterns:
        locators = [
            page.get_by_role("button", name=pattern),
            page.get_by_role("link", name=pattern),
            page.get_by_text(pattern),
        ]
        for locator in locators:
            try:
                for i in range(min(locator.count(), 12)):
                    item = locator.nth(i)
                    if item.is_visible(timeout=400):
                        item.click(timeout=3000)
                        page.wait_for_timeout(1000)
                        return True
            except Exception:
                pass
    return False


def choose_store(page, store_name: str) -> bool:
    config = STORES[store_name]
    city = config["city"]
    aliases = config.get("aliases", [store_name, city])
    opened = click_store_picker(page)
    if not opened:
        print(f"STORE PICKER NOT OPENED {store_name}")

    # XL-BYGG og enkelte andre kjeder bruker forskjellig placeholder i modalvinduet.
    selectors = [
        "input[placeholder*='Søk' i]",
        "input[placeholder*='søk' i]",
        "input[placeholder*='butikk' i]",
        "input[placeholder*='varehus' i]",
        "input[placeholder*='Hvor' i]",
        "input[aria-label*='Søk' i]",
        "input[type='search']",
    ]
    for selector in selectors:
        try:
            inputs = page.locator(selector)
            for i in range(min(inputs.count(), 8)):
                inp = inputs.nth(i)
                if inp.is_visible(timeout=300):
                    inp.fill(city)
                    page.wait_for_timeout(1400)
                    break
        except Exception:
            pass

    names = aliases + [store_name, city]
    for name in names:
        candidates = [
            page.get_by_text(name, exact=True),
            page.get_by_role("button", name=re.compile(re.escape(name), re.I)),
            page.get_by_text(re.compile(r"\b" + re.escape(name) + r"\b", re.I)),
        ]
        for locator in candidates:
            try:
                for i in range(min(locator.count(), 15)):
                    item = locator.nth(i)
                    if item.is_visible(timeout=300):
                        item.click(timeout=3000)
                        page.wait_for_timeout(2200)
                        print(f"STORE SELECTED {store_name} via {name}")
                        return True
            except Exception:
                pass

    # Siste forsøk for XL-BYGG: velg en synlig rad/knapp som inneholder Skogn.
    if store_name == "XL-BYGG Skogn":
        try:
            loc = page.locator("button, a, [role='button'], [role='option']").filter(has_text=re.compile(r"Skogn", re.I))
            for i in range(min(loc.count(), 10)):
                item = loc.nth(i)
                if item.is_visible(timeout=300):
                    item.click(timeout=3000)
                    page.wait_for_timeout(2200)
                    print("STORE SELECTED XL-BYGG Skogn via fallback")
                    return True
        except Exception:
            pass

    print(f"STORE SELECT NOT CONFIRMED {store_name}")
    return False


def discover_links(page, category_url: str, dimension: str, kind: str):
    try:
        page.goto(category_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1800)
        for _ in range(8):
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
            if kind == "imp" and not any(x in low for x in ("imp", "cuimp", "cu-imp", "ntr", "trykkimp")):
                continue
            if kind == "grunnet" and not any(x in low for x in ("grun", "grunn", "malt", "visir")):
                continue
            absolute = urljoin(category_url, href)
            if absolute.startswith("http") and absolute not in links:
                links.append(absolute)
        except Exception:
            continue
    return links[:12]


def scrape_product(page, store_name, url, dimension, kind):
    print(f"CHECK {store_name} {dimension} {kind} {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1800)
    selected = choose_store(page, store_name)
    page.wait_for_timeout(1800)
    text = visible_text(page)

    if not dimension_matches(text[:25000], dimension):
        print(f"NO DIMENSION {dimension}: {url}")
        return None, None, selected

    price, unit = parse_product_price(text)
    if price is None:
        price, unit = jsonld_price(page)
    if price is None:
        print(f"NO PRODUCT PRICE {store_name} {dimension}: {url}")
    else:
        print(f"FOUND {store_name} {dimension} {kind}: {price:.2f} / {unit}")
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
                        old_map[key]["status"] = "Sist kjente produktpris – ny kontroll feilet"
                        old_map[key]["checked_at"] = datetime.now(timezone.utc).isoformat()

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
