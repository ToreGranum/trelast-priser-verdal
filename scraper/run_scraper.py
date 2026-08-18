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

    patterns = [
        rf"(?:kr\s*)?{value_re}\s*(?:kr\s*)?(?:/\s*|per\s+|pr\.?\s*){unit_re}\b",
        rf"(?:kr\s*)?{value_re}\s*(?:kr\s*)?{unit_re}\b",
        rf"(?:/\s*|per\s+|pr\.?\s*){unit_re}\b[^0-9]{{0,60}}(?:kr\s*)?{value_re}",
    ]

    for i, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text, flags=re.I):
            groups = match.groups()
            if i == 2:
                unit, value = groups[0], groups[1]
            else:
                value, unit = groups[0], groups[1]
            price = number(value)
            if price is not None and 0 < price < 100000:
                return price, unit_name(unit)

    # Mange nettbutikker viser først bare «Pris» og deretter beløpet.
    for label in ("salgspris", "nettpris", "pris"):
        for match in re.finditer(label, text, flags=re.I):
            context = text[match.start():match.start() + 260]
            price_match = re.search(r"(?:kr\s*)?" + value_re, context, flags=re.I)
            if not price_match:
                continue
            price = number(price_match.group(1))
            if price is None or not 0 < price < 100000:
                continue
            unit_match = re.search(
                r"(?:/\s*|per\s+|pr\.?\s*)" + unit_re + r"\b",
                context,
                flags=re.I,
            )
            return price, unit_name(unit_match.group(1)) if unit_match else "stk"

    return None, None


# Bruk samme robuste talltolking som tidligere versjon.
scraper.parse_product_price = robust_parse_product_price


def _click_xl_store(page):
    """Velg XL-BYGG Skogn selv om varehusdialogen har en annen DOM enn OBS/Bygger'n."""
    if "XL-BYGG" not in str(page.url):
        return False

    # Åpne varehusvelgeren.
    patterns = [
        re.compile(r"^\s*Velg varehus\s*$", re.I),
        re.compile(r"Velg varehus", re.I),
    ]
    opened = False
    for pattern in patterns:
        for locator in (
            page.get_by_role("button", name=pattern),
            page.get_by_text(pattern),
        ):
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

    # Søkefeltet varierer mellom produksjons- og stagingversjonen.
    for selector in (
        "input[placeholder*='Søk' i]",
        "input[placeholder*='butikk' i]",
        "input[placeholder*='varehus' i]",
        "input[aria-label*='Søk' i]",
        "input[type='search']",
    ):
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

    # Prøv hele raden/knappen først. Deretter en eksplisitt «Velg»-knapp i raden.
    store_re = re.compile(r"(?:XL-BYGG\s*)?(?:Gunnar\s*T\.\s*Strøm.*)?Skogn", re.I)
    candidates = [
        page.get_by_text(store_re),
        page.locator("button, a, [role='button'], [role='option']").filter(has_text=store_re),
    ]
    for locator in candidates:
        try:
            for i in range(min(locator.count(), 20)):
                item = locator.nth(i)
                if not item.is_visible(timeout=250):
                    continue
                # Hvis dette er en container, klikk på nærmeste knapp inni den.
                try:
                    button = item.locator("xpath=ancestor::*[self::li or @role='option' or self::div][1]//button").first
                    if button.count() and button.is_visible(timeout=200):
                        button.click(timeout=4000)
                    else:
                        item.click(timeout=4000)
                except Exception:
                    item.click(timeout=4000)
                page.wait_for_timeout(2200)
                return True
        except Exception:
            pass

    # Noen versjoner viser bare «Skogn» som tekst og flere «Velg»-knapper.
    try:
        rows = page.locator("li, [role='option'], tr, .store, .warehouse, [class*='store' i]").filter(has_text=re.compile(r"Skogn", re.I))
        for i in range(min(rows.count(), 10)):
            row = rows.nth(i)
            if not row.is_visible(timeout=200):
                continue
            btn = row.get_by_role("button", name=re.compile(r"Velg|Velg varehus", re.I)).first
            if btn.count() and btn.is_visible(timeout=200):
                btn.click(timeout=4000)
                page.wait_for_timeout(2200)
                return True
    except Exception:
        pass

    return False


def robust_scrape_product(page, store_name, url, dimension, kind):
    print(f"CHECK {store_name} {dimension} {kind} {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1800)

    selected = False
    if store_name == "XL-BYGG Skogn":
        selected = _click_xl_store(page)

    # Bruk også den generelle butikkvelgeren for kjedene som støtter den.
    if not selected:
        try:
            selected = scraper.choose_store(page, store_name)
        except Exception as exc:
            print(f"STORE PICKER ERROR {store_name}: {exc}")

    # XL-BYGG kan laste pris/lager asynkront etter butikkvalg.
    page.wait_for_timeout(2500 if store_name == "XL-BYGG Skogn" else 1200)
    text = scraper.visible_text(page)

    if not scraper.dimension_matches(text[:30000], dimension):
        print(f"NO DIMENSION {dimension}: {url}")
        return None, None, selected

    price, unit = robust_parse_product_price(text)
    if price is None:
        price, unit = scraper.jsonld_price(page)

    # Fallback: pris kan ligge i aria-label/title eller skjult i en produkt-widget.
    if price is None:
        try:
            attrs = page.locator("[aria-label], [title]").evaluate_all(
                "els => els.map(e => (e.getAttribute('aria-label') || '') + ' ' + (e.getAttribute('title') || '')).join(' ')"
            )
            price, unit = robust_parse_product_price(attrs)
        except Exception:
            pass

    if price is None:
        print(f"NO PRODUCT PRICE {store_name} {dimension}: {url}")
    else:
        print(f"FOUND {store_name} {dimension} {kind}: {price:.2f} / {unit}")
    return price, unit, selected


scraper.scrape_product = robust_scrape_product
scraper.main()
