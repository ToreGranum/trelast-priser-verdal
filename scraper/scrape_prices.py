import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("data/prices.json")

# Produktkilder som er identifisert på kjedenes offentlige nettsteder.
# Lokal butikk velges i nettbutikken før pris leses. Dersom butikken ikke
# kan bekreftes, beholdes siste bekreftede lokalpris i stedet for å bruke
# en nasjonal/ukjent pris.
PRODUCTS = [
    {
        "store": "OBS BYGG Verdal",
        "url": "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/ubehandlet-konstruksjonsvirke/3019536",
        "dimension": "48x98", "type": "ubh"
    },
    {
        "store": "OBS BYGG Verdal",
        "url": "https://www.obsbygg.no/trelast-og-tyngre-byggevarer/treverk/konstruksjonsvirke/impregnert-konstruksjonsvirke-----0-2514104-2291725/3003426",
        "dimension": "48x98", "type": "imp"
    },
    {
        "store": "Bygger'n Verdal",
        "url": "https://www.byggern.no/product/54313798",
        "dimension": "48x98", "type": "ubh"
    },
    {
        "store": "Bygger'n Verdal",
        "url": "https://www.byggern.no/product/54295178",
        "dimension": "48x98", "type": "imp"
    },
    {
        "store": "XL-BYGG Skogn",
        "url": "https://www.xl-bygg.no/product/bergene-holm-gran-48x098x4800-k-virke-c24-500423674",
        "dimension": "48x98", "type": "ubh"
    },
]

STORE_SEARCH = {
    "OBS BYGG Verdal": "Verdal",
    "Bygger'n Verdal": "Verdal",
    "XL-BYGG Skogn": "Skogn",
}


def parse_price(text: str):
    # Vanlige formater: 41,90 / m, 41.90 per m, kr 41,90
    patterns = [
        r"(?:kr\s*)?(\d{1,5}[,.]\d{2})\s*(?:per|/)?\s*m\b",
        r"(?:kr\s*)?(\d{1,5}[,.]\d{2})\s*(?:kr)?\s*/\s*m\b",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.I)
        if m:
            return float(m.group(1).replace(".", "").replace(",", "."))
    return None


def choose_store(page, store_name: str):
    wanted = STORE_SEARCH[store_name]
    body = page.locator("body")
    text = body.inner_text(timeout=5000)
    if wanted.lower() in text.lower() and ("Velg butikk" not in text or store_name in text):
        return True

    # Best-effort interaction with common store selectors. Sites change these
    # selectors, so failure is treated as unverified rather than as a price.
    candidates = [
        "text=Velg butikk", "text=Velg varehus", "button:has-text('Velg butikk')",
        "button:has-text('Velg varehus')", "[aria-label*='butikk' i]"
    ]
    for selector in candidates:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1500):
                loc.click(timeout=2000)
                page.wait_for_timeout(700)
                break
        except Exception:
            pass

    for selector in ["input[placeholder*='Søk' i]", "input[placeholder*='butikk' i]", "input[type='search']"]:
        try:
            inp = page.locator(selector).first
            if inp.is_visible(timeout=1000):
                inp.fill(wanted)
                page.wait_for_timeout(700)
                page.get_by_text(wanted, exact=False).first.click(timeout=2000)
                page.wait_for_timeout(700)
                return store_name.lower() in page.locator("body").inner_text().lower()
        except Exception:
            pass
    return False


def scrape_one(page, item):
    page.goto(item["url"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1200)
    verified = choose_store(page, item["store"])
    text = page.locator("body").inner_text(timeout=10000)
    price = parse_price(text)
    return price if verified else None


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"items": []}
    old_map = {(x["store"], x["dimension"], x["type"]): x for x in old.get("items", [])}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="nb-NO")
        for item in PRODUCTS:
            key = (item["store"], item["dimension"], item["type"])
            previous = old_map.get(key, {})
            try:
                price = scrape_one(page, item)
            except Exception as exc:
                print(f"WARN {item['store']}: {exc}")
                price = None

            if price is not None:
                old_map[key] = {
                    **item,
                    "price_per_meter": price,
                    "verified_local": True,
                    "status": "Lokalpris bekreftet",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            elif previous.get("price_per_meter") is not None:
                old_map[key] = {
                    **previous,
                    "status": "Siste bekreftede lokalpris – ny sjekk feilet",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                old_map[key] = {
                    **item,
                    "price_per_meter": None,
                    "verified_local": False,
                    "status": "Ingen bekreftet lokalpris",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "items": list(old_map.values())}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
