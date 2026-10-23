# Shwapno Fresh Prices

Daily prices from [Shwapno](https://www.shwapno.com) for **fresh fruits, vegetables, fish, meat, poultry and eggs**, with a page to compare **nutrients per taka**.

- Collected every day at **9:00 AM Bangladesh time** by a GitHub Action.
- Only the **final price** is kept: if Shwapno has a discount running, the saved price already includes it.
- Each item is matched to reference nutrition values, so you can see things like "grams of protein per ৳100" or "cost per 100 g you actually eat".

## Where the data is

| File | What it holds |
|---|---|
| `data/latest.csv` | Today's prices. Opens in Excel or Google Sheets. |
| `data/daily/YYYY-MM-DD.csv` | One file per day, kept forever. |
| `data/latest.json` | Today's prices, used by the web page. |
| `data/history.json` | Every item's price on every day, used for the price-history chart. |

CSV columns: `date, category, name, pack, final_price_tk, price_per_kg_tk, in_stock, cost_per_100g_edible_tk, protein_g_per_100tk, kcal_per_100tk, url`

## The web page

`index.html` is the **Kacha Bazaar** page. Turn on GitHub Pages (Settings → Pages → Source: *Deploy from a branch* → `main` / `(root)`) and it is live at https://mishu1505084.github.io/daily-food-prices/.

- A table of every item: price, price per kg, then all nine nutrients (protein, calories, fat, carbs, fibre, calcium, iron, vitamin A, vitamin C).
- Switch the nutrient columns between **per 100 g** and **per ৳100 spent**, and click any column heading to sort by it. The top 10% in each column is green.
- Filter by category or search by name.
- Tap an item to see its nutrients per 100 g, per pack and per ৳100, plus its price history.
- Tick a few items and press **Compare** to see just those items in the same table layout (per 100 g or per ৳100 spent). The best value in each column is green.

## How it works

`scraper/scrape.py` reads the same JSON API the Shwapno website uses (`/api/category/products`) for these category pages: `fresh-fruits`, `fresh-vegetables`, `fish`, `meat`, `eggs`, plus their parents `fruits-and-vegetables` and `meat-and-fish` to catch items like packaged dates and dried fish. It uses only the Python standard library.

- `priceValue` from the API is the price after any discount, so that is the number saved.
- Items sold by weight are converted to a price per kg. Items sold by the piece use the weight in the name (e.g. "600gm+", "12Pcs"), or a typical piece weight from the nutrition table (shown as an estimate on the page).
- Chicken, duck, pigeon and quail are labelled **Poultry**. Beef and mutton are **Meat**.

### Nutrition values

`scraper/nutrition.json` has one rule per food. Each rule has:

- `match`: name patterns, checked top to bottom (the first match wins).
- `n`: nutrients per 100 g of the edible part, raw.
- `edible`: the share of the bought weight you actually eat. For example, whole rui is about 58% edible once the head, bones and scales are gone. This keeps bone-in fish and meat comparable with boneless cuts.
- `piece_g`: a typical weight for items sold by the piece or bunch.

The values are typical reference figures from USDA FoodData Central and the Food Composition Table for Bangladesh (2013), rounded. They are **approximate**: real nutrients vary with breed, season and size. Shwapno doesn't publish nutrition labels for fresh food.

When Shwapno adds a new item that matches no rule, the daily log prints `No nutrition match for: …`. To fix it, add or extend a rule in `nutrition.json`.

## Running it yourself

```bash
python scraper/scrape.py              # writes into data/
python -m http.server                 # then open http://localhost:8000
```

To run the GitHub Action by hand: **Actions → Daily Shwapno prices → Run workflow**.

## Notes

- Prices are Shwapno's default online prices. Prices in a particular store or delivery area may differ.
- GitHub sometimes starts scheduled runs a few minutes late, and it pauses scheduled workflows in repos with no activity for 60 days. The daily data commit counts as activity, so this shouldn't happen while the scraper keeps working.
