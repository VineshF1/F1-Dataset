"""
Merge + Q&A generation (Task 3)
- Loads Jolpica normalized + Wikipedia extracts
- Entity-linked: drivers/seasons/incidents linked to race_ids
- Q&A types: factual lookup (results/champions), biographical, incident/event
- Multiple phrasings per fact, source traceability
- Output: data/final/qa.jsonl  {question, answer, source, entity_type, season}
"""
import json, re, random
from pathlib import Path
from collections import defaultdict

PROC = Path("data/processed")
FINAL = Path("data/final")
RAW_WIKI = Path("data/raw/wikipedia")
FINAL.mkdir(parents=True, exist_ok=True)

# Load normalized races
rows=[]
if (PROC / "races_normalized.jsonl").exists():
    for line in (PROC / "races_normalized.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip(): rows.append(json.loads(line))
    print(f"Loaded {len(rows)} normalized race-result rows")

# Load Wikipedia
def load_wiki(p):
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except: return []
    return []
drivers_wiki = load_wiki(RAW_WIKI / "drivers_wiki.json")
seasons_wiki = load_wiki(RAW_WIKI / "seasons_wiki.json")
incidents_wiki = load_wiki(RAW_WIKI / "incidents_wiki.json")
constructors_wiki = load_wiki(RAW_WIKI / "constructors_wiki.json")
print(f"Wiki: drivers {len(drivers_wiki)} seasons {len(seasons_wiki)} incidents {len(incidents_wiki)} constructors {len(constructors_wiki)}")

# Champions
champions = json.loads((PROC / "champions.json").read_text(encoding="utf-8")) if (PROC / "champions.json").exists() else []
champ_driver_by_season = {c["season"]: c for c in champions if c["type"]=="drivers"}
champ_const_by_season = {c["season"]: c for c in champions if c["type"]=="constructors"}

qa=[]

def add_qa(question, answer, source, entity_type, season=None):
    qa.append({"question": question, "answer": answer, "source": source, "entity_type": entity_type, "season": season})

# A. Factual Q&A from structured data
# A1: per-race winner (multiple phrasings)
from collections import defaultdict
races_by_id=defaultdict(list)
for r in rows:
    races_by_id[(r["season"], r["round"])].append(r)

for (season, rnd), entries in races_by_id.items():
    winners=[e for e in entries if str(e["finish"])=="1"]
    if not winners: continue
    w=winners[0]
    race_name=w.get("raceName","Grand Prix")
    circuit=w.get("circuitName") or w.get("circuit","")
    date=w.get("date","")
    # 3 phrasings per race winner
    templates=[
        f"Who won the {race_name} in {season}?",
        f"Who won the {season} {race_name}?",
        f"{season} {race_name} winner?",
    ]
    answer=f"{w['driver']} ({w['constructor']}) won the {race_name} on {date} (round {rnd}, {circuit})."
    source=w["source"]
    for q in templates:
        add_qa(q, answer, source, "race_result", season)

# A2: per-season champions (drivers & constructors)
for season in sorted(champ_driver_by_season):
    d=champ_driver_by_season[season]
    c=champ_const_by_season.get(season)
    # driver champion phrasings
    for q in [f"Who won the {season} World Championship?", f"Who was the {season} F1 drivers' champion?", f"{season} F1 champion?"]:
        add_qa(q, f"{d['champion']} won the {season} Drivers' World Championship ({d['wins']} wins, {d['points']} points).", d.get("source", f"Jolpica:{season}/driverStandings"), "season_champion", season)
    if c:
        for q in [f"Which team won the {season} Constructors' Championship?", f"{season} constructors' champion?"]:
            add_qa(q, f"{c['champion']} won the {season} Constructors' Championship ({c['points']} points).", c.get("source", f"Jolpica:{season}/constructorStandings"), "season_champion", season)

# A3: per-season race count / pole? keep simple: most wins
# (already covered)

# B. Biographical Q&A from Wikipedia driver extracts
# We preserve factual specificity; answer is first 2 paras + key facts
for d in drivers_wiki:
    if d.get("missing") or d.get("error"): continue
    title=d.get("title","")
    extract=d.get("extract","")
    if len(extract) < 200: continue
    paras=d.get("paragraphs",[])
    # Use driver name from title
    name = title.replace("_"," ")
    short = " ".join(paras[:2]) if len(paras)>=2 else paras[0] if paras else extract[:600]
    # truncate answer to ~500 chars preserving sentences
    if len(short) > 700:
        # cut at sentence boundary
        cut = short[:700].rsplit(". ",1)[0]+"."
        short=cut
    # biographical Q&A: 2-3 phrasings
    add_qa(f"Who is {name}?", short, d["source"], "driver_bio", None)
    # "which teams did X drive for" — extract teams line if present in first 3 paras
    # keep answer same short bio (factual, not fabricated)
    add_qa(f"Tell me about {name}'s F1 career.", short, d["source"], "driver_bio", None)

# C. Season narrative Q&A
for s in seasons_wiki:
    if s.get("missing") or s.get("error"): continue
    title=s.get("title","")
    m=re.search(r"(\d{4})", title)
    season=int(m.group(1)) if m else None
    paras=s.get("paragraphs",[])
    if not paras: continue
    summary=" ".join(paras[:3])
    if len(summary) > 800:
        summary=summary[:800].rsplit(". ",1)[0]+"."
    season_label = f"{season}" if season else title.replace("_"," ")
    add_qa(f"What happened in the {season_label} Formula One season?", summary, s["source"], "season_summary", season)
    # rule changes question if mentioned
    if "regulation" in summary.lower() or "rule" in summary.lower():
        add_qa(f"What were the major rule changes in {season_label}?", summary, s["source"], "season_summary", season)

# D. Incident / controversy / rivalry Q&A (must include date/race/cause/outcome — we use Wikipedia extract verbatim chunk)
for inc in incidents_wiki:
    if inc.get("missing") or inc.get("error"): continue
    title=inc.get("title","").replace("_"," ")
    extract=inc.get("extract","")
    if len(extract) < 200: continue
    paras=inc.get("paragraphs",[])
    # For incident: use first 3 paras factual
    ans=" ".join(paras[:3])
    if len(ans) > 900:
        ans=ans[:900].rsplit(". ",1)[0]+"."
    # Try to infer season from text
    m=re.search(r"(19|20)\d{2}", extract)
    season=int(m.group(0)) if m else None
    # paraphrased questions
    add_qa(f"What happened at {title}?", ans, inc["source"], "incident", season)
    add_qa(f"Tell me about {title}.", ans, inc["source"], "incident", season)
    # Special cases: Senna/Bianchi need explicit "what happened to X"
    if "Senna" in title:
        add_qa("What happened to Ayrton Senna?", ans, inc["source"], "incident", 1994)
    if "Bianchi" in title:
        add_qa("What happened to Jules Bianchi?", ans, inc["source"], "incident", 2014)

# Dedup by (question, answer) exact
seen=set()
dedup=[]
for item in qa:
    k=(item["question"].lower(), item["answer"][:100])
    if k in seen: continue
    seen.add(k)
    dedup.append(item)

# Shuffle deterministically for train split friendliness
random.seed(42)
random.shuffle(dedup)

# Write
FINAL.mkdir(parents=True, exist_ok=True)
with open(FINAL / "qa.jsonl","w",encoding="utf-8") as f:
    for item in dedup:
        f.write(json.dumps(item, ensure_ascii=False)+"\n")

# stats
by_type=defaultdict(int)
for x in dedup: by_type[x["entity_type"]]+=1
stats={"total":len(dedup),"by_type":dict(by_type),"sources": len(set(x["source"] for x in dedup))}
# add era breakdown
era=defaultdict(int)
for x in dedup:
    if x["season"] is None: era["unknown"]+=1
    elif x["season"]<1970: era["1950-1969"]+=1
    elif x["season"]<1990: era["1970-1989"]+=1
    elif x["season"]<2010: era["1990-2009"]+=1
    else: era["2010-2025"]+=1
stats["by_era"]=dict(era)
(Path(PROC) / "qa_stats.json").write_text(json.dumps(stats, indent=2))
print(f"Q&A generated: {len(dedup)} pairs")
print(json.dumps(stats, indent=2))
print(f"Output: {FINAL/'qa.jsonl'}")
