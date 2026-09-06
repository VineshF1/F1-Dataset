# Training Guide — F1-Dataset

> Point to **one file**: `data/final/qa.jsonl` (10656 pairs). Don't point to folder — `data/` is 139M raw.

## Rebuild

```bash
pip install requests wikipedia-api
python pipeline/01_fetch_jolpica_bulk.py  # 19 min, 104M raw, offset+=100 paginated
python pipeline/fast_normalize.py         # dedup 25784
python pipeline/02_fetch_wikipedia.py     # 881 drivers + 76 seasons
python pipeline/05_add_paddock_knowledge.py  # 30 persons + 38 knowledge → 5816
python pipeline/06_expand_dataset.py      # qual 2039 + circuits 177 + h2h 80 + 5× 2298 + regs 8 + career_total 239 → 10656
```
