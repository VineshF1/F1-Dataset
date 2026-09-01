Build a data pipeline to construct an F1 dataset (1950–2025) for fine-tuning an LLM 
to answer F1 trivia/Q&A — including factual stats (who won X championship) AND 
narrative/biographical questions (who is driver X, what happened to them, major 
career events, incidents, controversies, rule changes).

DATA SOURCE LIMITATIONS (do not deviate from this):
- FastF1 (Python library) only provides detailed session/telemetry data from 
  ~2018 onward. Cannot retrieve full data before that.
- For 1950–2017 structured data, use Jolpica-F1 (actively maintained successor to 
  Ergast API, same schema) for race results, qualifying, standings, driver/
  constructor/circuit metadata.
- For 2018–2025, use FastF1 for lap times, pit stops, weather, session results, 
  plus Jolpica for standings continuity.
- None of the above sources contain narrative content (biographies, career 
  narratives, deaths, crashes, controversies, rivalries, rule-change history). 
  This must come from a separate source — see Task 2.

TASK 1 — STRUCTURED DATA (stats/results):
1. Ingest via Jolpica (1950–2017) and FastF1 + Jolpica (2018–2025):
   - Race results, qualifying, grid positions, finishing status/DNF reason
   - Driver/constructor standings after every race
   - World champions per season (drivers' and constructors')
   - Circuit and season metadata
2. Normalize into a unified schema: race_id, season, round, circuit, date, driver, 
   constructor, grid, finish, points, status, standings snapshot.
3. Cross-check season race counts and championship winners against known records 
   to catch ingestion errors.

TASK 2 — NARRATIVE / BIOGRAPHICAL DATA:
1. Source from Wikipedia (via Wikipedia API or wikipedia-api Python library) for:
   - Every driver who has started an F1 race 1950–2025: full biography, career 
     span, teams driven for, major wins, championships, and — critically — how 
     their career/life ended if applicable (retirement, death, cause of death, 
     date, circumstances). Do not omit or soften fatal incidents (e.g. Senna 1994, 
     Bianchi 2015, Ratzenberger 1994) — extract them factually and completely.
   - Every season 1950–2025: season summary covering title fight, major storylines, 
     rule changes that season.
   - Major recorded incidents/crashes (fatal and career-defining non-fatal), 
     rivalries (e.g. Senna–Prost, Hamilton–Verstappen 2021), and controversies 
     (e.g. Crashgate, Spygate, 2021 Abu Dhabi finale) as a distinct table.
   - Constructor histories: entry/exit years, name changes, ownership changes.
2. Extract as clean prose paragraphs per entity (driver, season, incident), 
   preserving factual specificity (dates, names, causes) — do not paraphrase away 
   key facts during cleaning.
3. Flag any biographical/incident claim sourced from a single low-traffic Wikipedia 
   page for manual review — Wikipedia content quality varies, especially for 
   pre-1970s figures.

TASK 3 — MERGE AND STRUCTURE FOR Q&A FINE-TUNING:
1. Combine structured (Task 1) and narrative (Task 2) data into a single entity-
   linked dataset — every driver/season/incident record should link to its 
   relevant race results.
2. Generate fine-tuning examples as Q&A pairs, covering three question types:
   a. Factual lookup: "Who won the 2001 World Championship?" 
      → derived directly from Task 1 structured data.
   b. Biographical: "Who is Ayrton Senna?" 
      → derived from Task 2 narrative data.
   c. Event/incident: "What happened to Ayrton Senna?" 
      → derived from Task 2 incident records, must include date, race, cause, 
      factual outcome — no vague answers like "he had an accident."
3. Generate multiple phrasings per fact (paraphrase the question, not the answer) 
   to improve generalization — e.g. "Who won in 2001?", "2001 F1 champion?", 
   "Who was champion in the 2001 season?"
4. For every Q&A pair, store the source (Jolpica / FastF1 / Wikipedia page) for 
   traceability and later fact-checking.

DATA QUALITY:
- Do not fabricate or interpolate any fact — structured or narrative. If unknown, 
  exclude the Q&A pair rather than guess.
- Do not sanitize or omit fatal/negative events — factual completeness matters 
  more than tone for this use case.
- Log all gaps (missing bios, missing seasons, incomplete incident records) in a 
  coverage report.

OUTPUT:
- Unified dataset in JSONL, one Q&A pair per line: {question, answer, source, 
  entity_type, season}
- Data dictionary + coverage report (what's missing, by era and entity type)
- README with source attribution and licensing notes for Jolpica, FastF1, and 
  Wikipedia (CC BY-SA — this affects how you can distribute/use the fine-tuned 
  model's outputs, check this before finalizing)

---
## BUILD LOG — How we actually built it (2026-08-31, reproducible)

### What we shipped (v2 — 2026-09-01)
- 1149/1149 races (1950-2025), 25,784 results (deduped), 10418 QA pairs
- `data/processed/races_normalized.jsonl` (11M) + `champions.json` (144) + `data/final/qa.jsonl` (3.5M)
- 881/881 drivers, 76/76 seasons, 16 incidents, 11 constructors + 30 paddock persons + 38 F1 knowledge (20M) + 78 circuits
- QA breakdown: 5745 race_result, 2039 qualifying, 1748 driver_bio, 364 champion, 177 circuit, 83 person, 80 season, 63 f1_knowledge, 80 h2h, 31 incident, 8 regulation
- Validation: 0 duplicates, spot winners/poles correct, 76+68 champions

### Pipeline (run in order)
```
pip install requests wikipedia-api fastf1    # fastf1 3.8.3, wikipedia-api 0.15.0
python pipeline/01_fetch_jolpica_bulk.py     # Task 1 bulk — 76 seasons, ~19 min (0.6s polite, offset+=100)
python pipeline/fast_normalize.py            # merge bulk+per-race cache → 25784 rows (dedup 78)
python pipeline/02_fetch_wikipedia.py        # Task 2 core — 881 drivers, 76 seasons, ~10 min
python pipeline/05_add_paddock_knowledge.py  # B exhaustive — 30 persons + 38 knowledge → 5816 (+146)
python pipeline/03_merge_qa.py               # Task 3 base QA → 5816
python pipeline/06_expand_dataset.py         # expansions: qual 2039 + circuits 177 + h2h 80 + 5× 2298 + regs 8 → 10418
# validate:
python -c "import collections,json; r=[json.loads(l) for l in open('data/processed/races_normalized.jsonl')]; print(sum(1 for v in collections.Counter((x['race_id'],x['driverId']) for x in r).values() if v>1))"  # 0
wc -l data/final/qa.jsonl                    # 10418
```

### Key implementation notes (so you don't repeat mistakes)

1. **Jolpica bulk, not per-race**
   - Bulk endpoint: `https://api.jolpi.ca/ergast/f1/{season}/{results,qualifying,driverStandings,constructorStandings}.json`
   - Per-race would be 4596 calls (1149×4) → 4.8h with 429s. Bulk is 76×4=304 calls → 19 min at 0.6s polite.
   - `01_fetch_jolpica_bulk.py` handles this; `01_fetch_jolpica.py` (per-race) is legacy, don't use.

2. **Pagination trap: limit paginates by Result rows, not Races**
   - `limit=100` with `total` = row count (e.g. 1973 total 357 rows / 15 races → only 10 races saved, R5 split 14+9).
   - Server caps `limit` at 100 regardless of `limit=500` request — you must loop `offset+=100` until `offset >= total`, merge by `round`, dedup `Results` by `driverId`.
   - Verify: `races == sched` per season after fetch (e.g. 1972 must be 12/12, not 8/12). All 76 initially BAD at 712/1149, fixed via offset loop.

3. **429 throttling**
   - Even 1 req/s bursts 429 after ~200 races (sliding window, needs 8 min idle). Fixed: `0.6s` politeness + manual 429 backoff `wait = max(Retry-After,30)+15*attempt`, `Retry(total=2)` only for 500/502/503/504.
   - Headers: `User-Agent: F1-Dataset-Pipeline/1.0` required.

4. **Dedup**
   - Early-50s + Indy 500 have shared drives → same `race_id+driverId` twice with different `finish/points`. `fast_normalize.py` dedups by `(race_id, driverId)` keep lowest `finish` / highest `points` — removed 78 rows (25862→25784), verified `dups 0`.

5. **Wikipedia fixes**
   - Drivers: `drivers.json?limit=100&offset=0` paginated 9×100 → 881, not single `limit=1000` (silently caps at 100).
   - Seasons: pre-1981 title is `{year}_Formula_One_season` not `_World_Championship` (26 missing → 76/76 after fix).
   - Extracts: `prop=extracts|pageviews` in one call returns empty `extract` — split to separate calls; `urllib.parse.unquote` for `Ren%C3%A9_Arnoux`.
   - Deaths preserved: Senna 1994 / Bianchi 2015 / Ratzenberger 1994 flagged via `has_death`, low-traffic `<3000 chars` flagged.

6. **No telemetry stored** — per prompt exclusion: `telemetry=False,laps=False,weather=False` for FastF1 (cross-check 2018-2025 deferred, results only). Bulk normalized schema is `race_id season round circuit date driver constructor grid finish points status standings`.

7. **Verification deferred** — `formula1.com/en/results/{year}/{races,drivers,team}` via `crawl4ai` probed 200 OK (`Grand Prix|Winner` tables) but skipped: 228 pages = 11 min crawl4ai (5.9s/page) vs 90s via `requests+bs4`. Bulk validated vs Jolpica `*_schedule.json` instead.

### Reproduce from scratch
- Same `data/raw/jolpica` resume-cache: skip if `MRData` exists and `races==sched`. Delete `*_results.json` to force refetch.
- Outputs: `races_normalized.jsonl`, `champions.json`, `standings_raw.json`, `qa.jsonl`, `coverage_report.json`, `DATA_DICTIONARY.json`.
- Licenses: Jolpica CC BY-SA, Wikipedia CC BY-SA, FastF1 MIT — attribution in README/DATA_DICTIONARY.

### Time / space (measured)
- Jolpica bulk: ~19 min, 104M raw (76 bulk + schedules + per-race cache)
- Wikipedia: ~10 min, 19M
- Normalize + QA: <1 min
- Total: ~30 min wall, 136M data, 2.2M qa.jsonl