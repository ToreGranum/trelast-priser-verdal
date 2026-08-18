import re

import scrape_prices as base


def _parse_number(value):
    value = str(value).replace("\u00a0", " ").strip()
    if re.fullmatch(r"\d{1,6}\s+\d{2}", value):
        whole, cents = value.split()
        return float(f"{whole}.{cents}")
    try:
        return float(value.replace(" ", "").replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _unit(value):
    value = value.lower()
    if value in {"stk", "stykk", "enhet"}:
        return "stk"
    if value in {"pk", "pakke"}:
        return "pakke"
    return "m"


def parse_product_price(text: str):
    """Parse the concrete product price without converting units.

    OBS and some other stores render a decimal price as separate text nodes,
    e.g. ``41`` + ``90`` + ``per m``. The old parser missed that format.
    """
    cleaned = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()

    units = r"stk|stykk|enhet|pakke|pk|m|meter|lm|løpemeter"

    # Most reliable: price immediately followed by an explicit unit.
    patterns = [
        rf"(?:kr\s*)?(\d{{1,6}}(?:[.,]\d{{1,2}})?)\s*(?:kr\s*)?(?:/\s*|per\s+|pr\.?\s*)({units})\b",
        rf"(?:kr\s*)?(\d{{1,6}})\s+(\d{{2}})\s*(?:kr\s*)?(?:/\s*|per\s+|pr\.?\s*)({units})\b",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, cleaned, flags=re.I):
            if len(match.groups()) == 2:
                price = _parse_number(match.group(1))
                unit = _unit(match.group(2))
            else:
                price = _parse_number(f"{match.group(1)} {match.group(2)}")
                unit = _unit(match.group(3))
            if price is not None and 0 < price < 100000:
                return price, unit

    # Labelled prices: "Pris 41 90" / "Salgspris 41,90".
    for label in ("salgspris", "nettpris", "pris"):
        for match in re.finditer(label, cleaned, flags=re.I):
            context = cleaned[match.start():match.start() + 180]
            price_match = re.search(
                rf"(?:kr\s*)?(\d{{1,6}})\s+(\d{{2}})(?:\s*kr)?\s*(?:/\s*|per\s+|pr\.?\s*)({units})\b",
                context,
                flags=re.I,
            )
            if price_match:
                price = _parse_number(f"{price_match.group(1)} {price_match.group(2)}")
                if price and 0 < price < 100000:
                    return price, _unit(price_match.group(3))
            price_match = re.search(
                rf"(?:kr\s*)?(\d{{1,6}}(?:[.,]\d{{1,2})?))\s*(?:kr)?\s*(?:/\s*|per\s+|pr\.?\s*)({units})\b",
                context,
                flags=re.I,
            )
            if price_match:
                price = _parse_number(price_match.group(1))
                if price and 0 < price < 100000:
                    return price, _unit(price_match.group(2))

    # Last fallback for pages where the unit is separated from the price.
    # Only accept a two-part decimal when "per m/stk/pakke" is close by.
    for match in re.finditer(r"(\d{1,6})\s+(\d{2})\s*(?:kr\s*)?(?:/\s*|per\s+|pr\.?\s*)(%s)\b" % units, cleaned, flags=re.I):
        price = _parse_number(f"{match.group(1)} {match.group(2)}")
        if price and 0 < price < 100000:
            return price, _unit(match.group(3))

    for match in re.finditer(r"(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:kr\s*)?(?:/\s*|per\s+|pr\.?\s*)(%s)\b" % units, cleaned, flags=re.I):
        price = _parse_number(match.group(1))
        if price and 0 < price < 100000:
            return price, _unit(match.group(2))

    return None, None


# Replace the parser used by base.main().
base.parse_product_price = parse_product_price

if __name__ == "__main__":
    base.main()
