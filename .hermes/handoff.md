# Handoff — F1-Dataset 1950-2025

**Session:** 2026-09-01 continuous. Read `.hermes/F1-Dataset.md` BUILD LOG for full reproduce.

## Current state (v2)
- **Data:** 1149/1149 races (100%), 25784 rows (deduped 78, dups 0), 10418 QA (was 5670)
- QA: 5745 race_result, 2039 qualifying, 1748 driver_bio, 364 champion, 177 circuit, 83 person, 80 season, 63 f1_knowledge, 80 h2h, 31 incident, 8 regulation
- Files: `data/processed/races_normalized.jsonl` 11M, `data/final/qa.jsonl` 3.5M, `champions.json` 144, `data 139M`
- Pipeline: `01_fetch_jolpica_bulk.py` (0.6s offset+=100), `fast_normalize.py`, `02_fetch_wikipedia.py`, `05_add_paddock_knowledge.py` (30 persons +38 knowledge), `03_merge_qa.py`, `06_expand_dataset.py` (qual+circuits+h2h+5×+regs)
- Validation: spot winners 1950/2023, poles, Horner 3 QAs (was 0), 76+68 champions, 0 dups
- Docs: `README.md` colorful mermaid (Ferrari red #DC0000 + outer #FFF1F2), `TRAINING.md` 10418 (train 9376/val 1042), `.gitignore` ships final+processed only
- Deferred: FastF1 cross-check 2018-2025 (no telemetry), formula1.com scrape (5.9s crawl4ai vs 0.4s bs4), radio memes (39k archive skipped)

## To continue next session
```bash
wc -l data/final/qa.jsonl  # 10418
python -c "import collections,json; r=[json.loads(l) for l in open('data/processed/races_normalized.jsonl')]; print(sum(1 for v in collections.Counter((x['race_id'],x['driverId']) for x in r).values() if v>1))"  # 0
# rebuild: python pipeline/01_fetch_jolpica_bulk.py → fast_normalize → 05 → 06
```

## Decisions
- Bulk not per-race (304 vs 4596 calls), limit=100 paginates by rows not Races → offset+=100 loop + round-dedup + races==sched
- No laps/weather/telemetry stored (user exclusion)
- B exhaustive: 30 persons exhaustive, 38/46 knowledge (8 title alias missing), 78 circuits
- 5 expansions last run: qual 1554+485, circuits 177, h2h 80, paraphrase 2298 (3x→5x), regs 8
- Radio focus dropped per user, Formula Dream 39k skipped

## Next if needed
- Missing knowledge aliases: `Glossary_of_Formula_One_terms` → `Glossary_of_Formula_One_terms` fetch redirect
- Hub push: `huggingface-cli upload Vinesh/f1-qa data/final/qa.jsonl`
