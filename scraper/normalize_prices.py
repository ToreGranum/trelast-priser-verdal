import json
from pathlib import Path

p = Path("data/prices.json")
d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"items": []}

for x in d.get("items", []):
    if not x.get("verified_local"):
        x["price_per_meter"] = None
        x["price_per_unit"] = None
        x["status"] = "Ikke publisert – lokal butikkpris ikke bekreftet"
        x["unit"] = "m"
    elif x.get("unit") in {"m", "meter", "lm", "løpemeter"} and x.get("price_per_unit") is not None:
        x["price_per_meter"] = x["price_per_unit"]
        x["unit"] = "m"

p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
