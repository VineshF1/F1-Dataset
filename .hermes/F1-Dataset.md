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