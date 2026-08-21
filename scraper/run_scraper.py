import json
import re

from scraper import scrape_prices as scraper


def number(s):
    s = str(s).replace("\u00a0", " ").strip()
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


def unit_name(u):
    u = str(u).lower().strip()
    if u in {"stk", "stykk", "enhet", "pcs", "piece"}:
        return "stk"
    if u in {"pk", "pakke", "pack"}:
        return "pakke"
    if u in {"m", "meter", "lm", "løpemeter"}:
        return "m"
    return u


def robust_parse_product_price(text):
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    unit_re = r"(stk|stykk|enhet|pcs|piece|pakke|pk|pack|m|meter|lm|løpemeter)"
    value_re = r"(\d{1,6}[.,]\d{2}|\d{1,6}\s+\d{2})"
    bad_re = re.compile(r"(?:førpris|før pris|ord\. pris|ordinær pris|medlemspris|coop-medlem|sparer|spar|rabatt|fra)", re.I)
    candidates = []
    patterns = [
        rf"(?:kr\s*)?{value_re}\s*(?:kr\s*)?(?:/\s*|per\s+|pr\.?\s*){unit_re}\b",
        rf"(?:kr\s*)?{value_re}\s*(?:kr\s*)?{unit_re}\b",
        rf"(?:/\s*|per\s+|pr\.?\s*){unit_re}\b[^0-9]{{0,60}}(?:kr\s*)?{value_re}",
    ]
    for pattern_index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text, flags=re.I):
            groups = match.groups()
            if pattern_index == 2:
                unit, value = groups[0], groups[1]
            else:
                value, unit = groups[0], groups[1]
            price = number(value)
            if price is None or not 0 < price < 100000:
                continue
            context = text[max(0, match.start() - 100):min(len(text), match.end() + 100)]
            if bad_re.search(context):
                continue
            candidates.append({"price": price, "unit": unit_name(unit)})
    # Prefer explicit price per meter. The old scraper preferred stk first,
    # which caused a stykkpris such as 301.92 to be shown instead of 62.90/m.
    for wanted_unit in ("m", "stk", "pakke"):
        matching = [c for c in candidates if c["unit"] == wanted_unit]
        if matching:
            return matching[0]["price"], matching[0]["unit"]
    for label in ("salgspris", "nettpris", "pris"):
        for match in re.finditer(label, text, flags=re.I):
            context = text[match.start():match.start() + 300]
            if bad_re.search(context[:100]):
                continue
            price_match = re.search(r"(?:kr\s*)?" + value_re, context, flags=re.I)
            if not price_match:
                continue
            price = number(price_match.group(1))
            if price is None or not 0 < price < 100000:
                continue
            unit_match = re.search(r"(?:/\s*|per\s+|pr\.?\s*)" + unit_re + r"\b", context, flags=re.I)
            return price, unit_name(unit_match.group(1)) if unit_match else "stk"
    return None, None

scraper.parse_product_price = robust_parse_product_price

scraper.KNOWN_PRODUCTS.extend([
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/ubehandlet-konstruksjonsvirke/3019166", "48x148", "ubh"),
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/ubehandlet-konstruksjonsvirke/3019328", "48x198", "ubh"),
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/impregnert-konstruksjonsvirke-----0-2514104-2291725/3003403", "48x148", "imp"),
    ("OBS BYGG Verdal", "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/impregnert-konstruksjonsvirke-----0-2514104-2291725/3003423", "48x198", "imp"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54236866", "48x148", "ubh"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54237025", "48x198", "ubh"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54177506", "48x148", "imp"),
    ("Bygger'n Verdal", "https://www.byggern.no/product/54177525", "48x198", "imp"),
])


def _click_xl_store(page):
    if "xl-bygg.no" not in str(page.url).lower():
        return False
    opened = False
    for pattern in (re.compile(r"^\s*Velg varehus\s*$", re.I), re.compile(r"Velg varehus", re.I)):
        for locator in (page.get_by_role("button", name=pattern), page.get_by_text(pattern)):
            try:
                for i in range(min(locator.count(), 10)):
                    item = locator.nth(i)
                    if item.is_visible(timeout=300):
                        item.click(timeout=4000)
                        page.wait_for_timeout(900)
                        opened = True
                        break
            except Exception:
                pass
            if opened:
                break
        if opened:
            break
    if not opened:
        return False
    for selector in ("input[placeholder*='Søk' i]", "input[placeholder*='butikk' i]", "input[placeholder*='varehus' i]", "input[aria-label*='Søk' i]", "input[type='search']"):
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                inp = loc.nth(i)
                if inp.is_visible(timeout=250):
                    inp.fill("Skogn")
                    page.wait_for_timeout(1200)
                    break
        except Exception:
            pass
    pattern = re.compile(r"(?:XL-BYGG\s*)?(?:Gunnar\s*T\.\s*Strøm.*)?Skogn", re.I)
    for locator in (page.get_by_text(pattern), page.locator("button, a, [role='button'], [role='option']").filter(has_text=pattern)):
        try:
            for i in range(min(locator.count(), 20)):
                item = locator.nth(i)
                if item.is_visible(timeout=250):
                    item.click(timeout=4000)
                    page.wait_for_timeout(2200)
                    print("STRICT STORE SELECTED XL-BYGG Skogn")
                    return True
        except Exception:
            pass
    print("STRICT STORE SELECT FAILED XL-BYGG Skogn")
    return False


def _strict_choose_store(page, store_name):
    if store_name == "XL-BYGG Skogn":
        return _click_xl_store(page)
    config = scraper.STORES[store_name]
    city = config["city"]
    exact_names = [store_name] + [x for x in config.get("aliases", []) if x.lower() != city.lower()]
    try:
        scraper.click_store_picker(page)
    except Exception:
        pass
    for selector in ("input[placeholder*='Søk' i]", "input[placeholder*='butikk' i]", "input[placeholder*='varehus' i]", "input[aria-label*='Søk' i]", "input[type='search']"):
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                inp = loc.nth(i)
                if inp.is_visible(timeout=250):
                    inp.fill(city)
                    page.wait_for_timeout(1200)
                    break
        except Exception:
            pass
    # Never click the generic city name; only an exact branch/store name.
    for name in exact_names:
        for locator in (page.get_by_text(name, exact=True), page.get_by_role("button", name=re.compile(r"^" + re.escape(name) + r"$", re.I)), page.get_by_role("option", name=re.compile(r"^" + re.escape(name) + r"$", re.I))):
            try:
                for i in range(min(locator.count(), 20)):
                    item = locator.nth(i)
                    if item.is_visible(timeout=250):
                        item.click(timeout=4000)
                        page.wait_for_timeout(2200)
                        print(f"STRICT STORE SELECTED {store_name}")
                        return True
            except Exception:
                pass
    print(f"STRICT STORE SELECT FAILED {store_name}")
    return False

scraper.choose_store = _strict_choose_store


def robust_scrape_product(page, store_name, url, dimension, kind):
    print(f"CHECK {store_name} {dimension} {kind} {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1800)
    selected = scraper.choose_store(page, store_name)
    page.wait_for_timeout(1800)
    text = scraper.visible_text(page)
    if not scraper.dimension_matches(text[:30000], dimension):
        print(f"NO DIMENSION {dimension}: {url}")
        return None, None, selected
    price, unit = robust_parse_product_price(text)
    if price is None:
        price, unit = scraper.jsonld_price(page)
    if price is None:
        print(f"NO PRODUCT PRICE {store_name} {dimension}: {url}")
    else:
        print(f"FOUND {store_name} {dimension} {kind}: {price:.2f} / {unit}")
    return price, unit, selected

scraper.scrape_product = robust_scrape_product
scraper.main()
