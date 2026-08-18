import re

from scraper import scrape_prices as scraper


def number(s):
    s = str(s).replace("\u00a0", " ").strip()
    # Playwright kan hente norske desimaltall som to tekstnoder:
    # "41" + "90" -> "41 90". Dette betyr 41,90, ikke 4190.
    if re.fullmatch(r"\d{1,6}\s+\d{2}", s):
        whole, cents = s.split()
        return float(f"{whole}.{cents}")

    s = s.replace(" ", "")
    if "," in s and "." in s:
        # Norsk format: 1.234,56
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
    u = u.lower()
    if u in {"stk", "stykk", "enhet"}:
        return "stk"
    if u in {"pk", "pakke"}:
        return "pakke"
    if u in {"m", "meter", "lm", "løpemeter"}:
        return "m"
    return u


def robust_parse_product_price(text):
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()

    # Nettbutikker kan splitte et norsk desimaltall i tekstuttrekket:
    # "41 90 per m". Fang både 41,90 / 41.90 og 41 90.
    unit_re = r"(stk|stykk|enhet|pakke|pk|m|meter|lm|løpemeter)"
    patterns = [
        rf"(?:kr\s*)?(\d{{1,6}}[.,]\d{{2}}|\d{{1,6}}\s+\d{{2}})\s*(?:kr\s*)?(?:/\s*|per\s+|pr\.?\s*){unit_re}\b",
        rf"(?:kr\s*)?(\d{{1,6}}[.,]\d{{2}}|\d{{1,6}}\s+\d{{2}})\s*(?:kr\s*)?{unit_re}\b",
        rf"(?:/\s*|per\s+|pr\.?\s*){unit_re}\b[^0-9]{{0,30}}(?:kr\s*)?(\d{{1,6}}[.,]\d{{2}}|\d{{1,6}}\s+\d{{2}})",
    ]

    for i, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text, flags=re.I):
            groups = match.groups()
            if i == 2:
                value, unit = groups[1], groups[0]
            else:
                value, unit = groups[0], groups[1]
            price = number(value)
            if price is not None and 0 < price < 100000:
                return price, unit_name(unit)

    # Prisetiketter uten enhet. Behold som stk fordi dette er selve produktets
    # salgspris, ikke en beregnet pris per meter.
    for label in ("salgspris", "nettpris", "pris"):
        for match in re.finditer(label, text, flags=re.I):
            context = text[match.start():match.start() + 220]
            price_match = re.search(r"(?:kr\s*)?(\d{1,6}[.,]\d{2}|\d{1,6}\s+\d{2})", context)
            if price_match:
                price = number(price_match.group(1))
                if price is not None and 0 < price < 100000:
                    unit_match = re.search(r"(?:/\s*|per\s+|pr\.?\s*)(stk|stykk|enhet|pakke|pk|m|meter|lm|løpemeter)\b", context, flags=re.I)
                    return price, unit_name(unit_match.group(1)) if unit_match else "stk"

    return None, None


scraper.parse_product_price = robust_parse_product_price
scraper.main()
