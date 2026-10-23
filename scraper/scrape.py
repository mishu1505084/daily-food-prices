"""Daily Shwapno price scraper for fresh food.

Pulls every product in Shwapno's fruit, vegetable, fish, meat and egg categories
from the same JSON API the website uses, keeps only the final (after-discount)
price, matches each item to reference nutrition data, and writes:

  data/latest.json            everything the dashboard needs
  data/latest.csv             today's prices as a spreadsheet
  data/daily/YYYY-MM-DD.csv   one file per day (never overwritten by later days)
  data/history.json           price per item per day, for trend charts

Standard library only, so it runs anywhere Python 3.9+ is installed.
"""

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://www.shwapno.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
NUTRITION_FILE = os.path.join(ROOT, "scraper", "nutrition.json")
DHAKA = timezone(timedelta(hours=6))

# (label, category page slug, fallback catalog id, is parent). Sub-categories come
# first so each item gets the most specific label; the parent pages afterwards only
# pick up what the sub-categories missed (e.g. packaged dates, dried fish).
CATEGORIES = [
    ("Fruits", "fresh-fruits", "65ed45e2e429af37f903ae07", False),
    ("Vegetables", "fresh-vegetables", "65ed45e2e429af37f903ae08", False),
    ("Fish", "fish", "65ed45e2e429af37f903ae0b", False),
    ("Meat", "meat", "65ed45e2e429af37f903ae0f", False),
    ("Eggs", "eggs", "65ed45e6e429af37f903ae3e", False),
    ("Vegetables", "fruits-and-vegetables", "65ed45e0e429af37f903adf1", True),
    ("Fish", "meat-and-fish", "65ed45e0e429af37f903adef", True),
]

FRUIT_KEYS = {
    "dates", "banana", "apple", "orange", "pomegranate", "guava", "pear", "grapes", "pineapple",
    "papaya", "coconut", "tamarind", "mango", "litchi", "watermelon", "jackfruit", "jujube",
    "sapodilla", "dragon_fruit", "kiwi", "strawberry", "melon",
}
POULTRY_KEYS = {
    "chicken", "chicken_keema", "chicken_breast", "chicken_breast_boneless", "chicken_leg",
    "chicken_roast", "chicken_skin", "chicken_sonali", "duck", "pigeon", "quail", "turkey",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries - 1:
                raise
            wait = 5 * 2 ** attempt
            print(f"  retry in {wait}s after error: {e}", file=sys.stderr)
            time.sleep(wait)


def catalog_id(slug, fallback):
    """Read the category id from the category page, so a site change doesn't break us."""
    try:
        html = fetch(f"{BASE}/{slug}")
        m = re.search(r'catalogId\\?"\s*:\s*\\?"([0-9a-f]{24})', html)
        if m:
            return m.group(1)
    except Exception as e:  # fall back to the id we know
        print(f"  could not read id for {slug}: {e}", file=sys.stderr)
    return fallback


def category_products(cid):
    page = 1
    while True:
        d = json.loads(fetch(f"{BASE}/api/category/products?id={cid}&pageNumber={page}"))
        yield from d.get("products") or []
        if not d.get("hasNextPage"):
            return
        page += 1
        time.sleep(0.5)


def load_nutrition():
    with open(NUTRITION_FILE, encoding="utf-8") as f:
        foods = json.load(f)["foods"]
    for food in foods:
        food["_re"] = [re.compile(p, re.I) for p in food["match"]]
    return foods


def match_food(name, foods):
    for food in foods:
        if any(r.search(name) for r in food["_re"]):
            return food
    return None


WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|gm|gram|g)\b\+?", re.I)
COUNT_RE = re.compile(r"(\d+)\s*(?:pcs|pieces|piece|pc)\b", re.I)


def pack_info(p, food):
    """Return (pack label, grams in what the price buys, grams-is-an-estimate)."""
    name = p["name"]
    if p.get("uomType") == 20:  # sold by weight
        opts = p.get("uomOptions") or []
        pre = next((o for o in opts if o.get("isPreSelected")), opts[0] if opts else None)
        grams = (pre or {}).get("unitValue") or 1000
        label = f"{grams / 1000:g} kg" if grams >= 1000 else f"{grams:g} g"
        return label, grams, False

    unit = (p.get("unit") or "piece").lower()
    count = COUNT_RE.search(name)
    weight = WEIGHT_RE.search(name)
    per_piece = food.get("piece_g") if food else None
    if count and int(count.group(1)) > 1:
        n = int(count.group(1))
        return f"{n} pcs", (n * per_piece if per_piece else None), True
    if weight:
        g = float(weight.group(1)) * (1000 if weight.group(2).lower() == "kg" else 1)
        approx = "+" in name[weight.start():weight.end() + 1]
        if unit == "piece":
            return f"1 pc (~{g:g} g)", g, approx
        return (f"{g / 1000:g} kg" if g >= 1000 else f"{g:g} g"), g, approx
    if per_piece:
        return f"1 {unit} (~{per_piece:g} g)", per_piece, True
    return f"1 {unit}", None, True


def categorise(label, is_parent, food):
    key = food["key"] if food else ""
    if key in POULTRY_KEYS:
        return "Poultry"
    if is_parent and key in FRUIT_KEYS:
        return "Fruits"
    if is_parent and label == "Fish" and key.startswith(("beef", "mutton", "lamb", "buffalo")):
        return "Meat"
    return label


def money(x):
    return round(x, 2) if x is not None else None


def scrape():
    foods = load_nutrition()
    now = datetime.now(DHAKA)
    items, seen = [], set()
    for label, slug, fallback, is_parent in CATEGORIES:
        cid = catalog_id(slug, fallback)
        n_before = len(items)
        for p in category_products(cid):
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            food = match_food(p["name"], foods)
            price = p["price"]["priceValue"]  # already the final, discounted price
            pack, grams, estimated = pack_info(p, food)
            per_kg = price * 1000 / grams if grams else None
            items.append({
                "id": p["id"],
                "sku": p.get("sku"),
                "name": p["name"].strip(),
                "category": categorise(label, is_parent, food),
                "pack": pack,
                "price": money(price),
                "price_per_kg": money(per_kg),
                "grams": grams,
                "grams_estimated": estimated,
                "in_stock": p.get("stock") == "InStock",
                "food": food["key"] if food else None,
                "url": f"{BASE}/{p['seName']}",
                "image": ((p.get("picture") or {}).get("smallDeviceUrl") or {}).get("imageUrl"),
            })
        print(f"{slug}: {len(items) - n_before} new items")
    if not items:
        sys.exit("No products returned - Shwapno may have changed its site.")
    items.sort(key=lambda i: (i["category"], i["name"].lower()))
    unmatched = [i["name"] for i in items if not i["food"]]
    if unmatched:
        print("No nutrition match for:", *unmatched, sep="\n  ")
    return now, items, foods


def value_columns(item, foods_by_key):
    """Cost per 100 g you actually eat, and protein / energy you get for ৳100."""
    food = foods_by_key.get(item["food"])
    if not food or not item["price_per_kg"]:
        return None, None, None
    edible_g_per_tk = 1000 * food["edible"] / item["price_per_kg"]
    return (
        round(100 / edible_g_per_tk, 1),
        round(food["n"]["protein"] * edible_g_per_tk, 1),
        round(food["n"]["kcal"] * edible_g_per_tk),
    )


def write_outputs(now, items, foods):
    os.makedirs(os.path.join(DATA, "daily"), exist_ok=True)
    date = now.strftime("%Y-%m-%d")
    foods_by_key = {f["key"]: f for f in foods}

    with open(os.path.join(DATA, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"date": date, "updated": now.isoformat(timespec="seconds"),
                   "source": BASE, "items": items}, f, ensure_ascii=False, indent=1)

    cols = ["date", "category", "name", "pack", "final_price_tk", "price_per_kg_tk",
            "in_stock", "cost_per_100g_edible_tk", "protein_g_per_100tk",
            "kcal_per_100tk", "url"]
    rows = []
    for i in items:
        cost, protein, kcal = value_columns(i, foods_by_key)
        rows.append([date, i["category"], i["name"], i["pack"], i["price"], i["price_per_kg"],
                     "yes" if i["in_stock"] else "no",
                     cost, protein, kcal, i["url"]])
    for path in (os.path.join(DATA, "latest.csv"), os.path.join(DATA, "daily", f"{date}.csv")):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)

    hist_path = os.path.join(DATA, "history.json")
    history = {}
    if os.path.exists(hist_path):
        with open(hist_path, encoding="utf-8") as f:
            history = json.load(f)
    for i in items:
        h = history.setdefault(i["id"], {"name": i["name"], "prices": []})
        h["name"] = i["name"]
        h["prices"] = [p for p in h["prices"] if p[0] != date]  # re-runs replace today's entry
        h["prices"].append([date, i["price"], i["price_per_kg"]])
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))

    by_cat = {}
    for i in items:
        by_cat[i["category"]] = by_cat.get(i["category"], 0) + 1
    print(f"{date}: saved {len(items)} items", by_cat)


if __name__ == "__main__":
    write_outputs(*scrape())
