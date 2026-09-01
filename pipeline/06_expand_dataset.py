"""06_expand_dataset — 5 expansions: qual, circuits, h2h, paraphrase, regs deep dive
Appends to data/final/qa.jsonl, updates coverage. No telemetry.
"""
import json, re, pathlib, requests, urllib.parse as _up, time
from collections import Counter, defaultdict

RAW = pathlib.Path("data/raw/jolpica")
FINAL = pathlib.Path("data/final")
PROC = pathlib.Path("data/processed")
WIKI_RAW = pathlib.Path("data/raw/wikipedia")
UA="F1-Dataset-Pipeline/1.0 (research; contact@example.com)"
API="https://en.wikipedia.org/w/api.php"

qa_path=FINAL/"qa.jsonl"
existing=[]
if qa_path.exists():
    for l in qa_path.read_text(encoding="utf-8").splitlines():
        if l.strip():
            try: existing.append(json.loads(l))
            except: pass
existing_q=set(q["question"].strip().lower() for q in existing)
print(f"Starting QA {len(existing)}")
new_qa=[]
def add_q(question, answer, source, entity_type, season=None):
    k=question.strip().lower()
    if k in existing_q: return False
    if not answer or len(answer)<40: return False
    row={"question":question,"answer":answer,"source":source,"entity_type":entity_type,"season":season}
    new_qa.append(row); existing_q.add(k); return True

# 1. QUALIFYING — pole from bulk qualifying
qual_added=0
for y in range(1950,2026):
    p=RAW/f"{y}_qualifying.json"
    if not p.exists(): continue
    try:
        d=json.loads(p.read_text(encoding="utf-8"))
        races=d.get("MRData",{}).get("RaceTable",{}).get("Races",[])
    except: continue
    for race in races:
        rnd=int(race.get("round",0))
        qr=race.get("QualifyingResults",[])
        if not qr: continue
        pole=qr[0]
        driver=f"{pole['Driver']['givenName']} {pole['Driver']['familyName']}"
        cons=pole["Constructor"]["name"]
        circ=race.get("Circuit",{}).get("circuitName") or race.get("circuitId","")
        raceName=race.get("raceName","Grand Prix")
        date=race.get("date","")
        q1=pole.get("Q1",""); q2=pole.get("Q2",""); q3=pole.get("Q3","")
        time_str=q3 or q2 or q1 or ""
        src=f"Jolpica:{y}/{rnd}/qualifying"
        # 3 phrasings per pole
        ans=f"{driver} ({cons}) took pole position for the {raceName} at {circ} on {date}" + (f" with {time_str}." if time_str else ".")
        for q in [f"Who took pole position at the {raceName} in {y}?", f"Who was on pole for the {y} {raceName}?", f"{y} {raceName} pole sitter?"]:
            if add_q(q, ans, src, "qualifying", y): qual_added+=1
        # bonus: qualifying time Q if asked
        if time_str and y>=1996:
            add_q(f"What was pole time at the {y} {raceName}?", f"Pole time was {time_str} by {driver} ({cons}).", src, "qualifying", y)

print(f"1. Qualifying added ~{qual_added}")

# 2. CIRCUITS — 78
try:
    circs=json.loads((RAW/"circuits.json").read_text(encoding="utf-8"))
    circuits=circs["MRData"]["CircuitTable"]["Circuits"]
except: circuits=[]
circ_added=0
for c in circuits:
    name=c.get("circuitName",""); cid=c.get("circuitId","")
    loc=c.get("Location",{}); country=loc.get("country",""); locality=loc.get("locality","")
    url=c.get("url","")
    # races at circuit
    src=f"Jolpica:circuits/{cid}"
    ans=f"{name} is a Formula One circuit in {locality}, {country} (circuitId: {cid}). Source: {url}"
    if add_q(f"Tell me about {name}.", ans, src, "circuit", None): circ_added+=1
    if add_q(f"Where is {name} located?", f"{name} is located in {locality}, {country}.", src, "circuit", None): circ_added+=1
    if country and add_q(f"Which country hosts {name}?", f"{name} is in {country}.", src, "circuit", None): circ_added+=1
# deduplicate expectation ~78*2, but cap
print(f"2. Circuits added {circ_added} (from {len(circuits)} circuits)")

# 3. HEAD-TO-HEAD — champion vs runner-up + iconic rivalries
# Build standings top2 per season from bulk driverStandings
h2h_added=0
# iconic manual pairs that fans ask
iconic=[
    ("Ayrton Senna","Alain Prost","1988"),("Ayrton Senna","Alain Prost","1989"),("Lewis Hamilton","Max Verstappen","2021"),
    ("Michael Schumacher","Mika Hakkinen","1998"),("Michael Schumacher","Mika Hakkinen","1999"),("Sebastian Vettel","Lewis Hamilton","2017"),
    ("Niki Lauda","James Hunt","1976"),("Fernando Alonso","Kimi Raikkonen","2005"),("Nigel Mansell","Ayrton Senna","1992"),
]
# season top2 from champions bulk standings
for y in range(1950,2026):
    p=RAW/f"{y}_driverStandings.json"
    if not p.exists(): continue
    try:
        d=json.loads(p.read_text(encoding="utf-8"))
        lists=d.get("MRData",{}).get("StandingsTable",{}).get("StandingsLists",[])
        if not lists: continue
        standings=lists[0].get("DriverStandings",[])
        if len(standings)<2: continue
        c1=standings[0]; c2=standings[1]
        n1=f"{c1['Driver']['givenName']} {c1['Driver']['familyName']}"; n2=f"{c2['Driver']['givenName']} {c2['Driver']['familyName']}"
        p1=c1["points"]; p2=c2["points"]; w1=c1["wins"]; w2=c2["wins"]
        src=f"Jolpica:{y}/driverStandings"
        q=f"Who finished ahead in {y}, {n1} or {n2}?"
        a=f"In {y}, {n1} finished ahead of {n2} ({p1} pts, {w1} wins vs {p2} pts, {w2} wins). Champion: {n1}."
        if add_q(q, a, src, "h2h", y): h2h_added+=1
        # reverse phrasing
        if y in [2021,1989,1976,1998]:
            q2=f"{n1} vs {n2} {y} — who won?"
            if add_q(q2, a, src, "h2h", y): h2h_added+=1
    except: pass
# iconic extra if not already covered
for a,b,y in iconic:
    # find if we already have h2h for that year containing both names
    pass
print(f"3. H2H added {h2h_added}")

# 4. PARAPHRASE augment 3x→5x for race_result wins: add 2 per race
# Find per-race winner rows
rows=[json.loads(l) for l in open(PROC/"races_normalized.jsonl",encoding="utf-8")]
by_race=defaultdict(list)
for r in rows: by_race[(r["season"],r["round"])].append(r)
para_added=0
for (season,rnd), entries in by_race.items():
    winners=[e for e in entries if str(e["finish"])=="1"]
    if not winners: continue
    w=winners[0]; raceName=w.get("raceName","Grand Prix"); circuit=w.get("circuitName") or ""
    date=w.get("date",""); driver=w["driver"]; cons=w["constructor"]
    src=w["source"]
    ans=f"{driver} ({cons}) won the {raceName} on {date} (round {rnd}, {circuit})."
    for q in [f"Winner of the {season} {raceName}?", f"Results of {season} Round {rnd} — who won the {raceName}?"]:
        if add_q(q, ans, src, "race_result", season): para_added+=1
print(f"4. Paraphrase added {para_added} (target 2298)")

# 5. REGULATIONS deep dive — 6 pages, 3 QAs each → ~18 plus History already 48k
reg_titles=["History_of_Formula_One_regulations","2022_Formula_One_World_Championship","2014_Formula_One_World_Championship","Ground_effect_(cars)","Hybrid_electric_vehicle","Budget_cap","Halo_(motor_sport)","Drag_reduction_system"]
# Use already fetched paddock_knowledge where possible, else fetch minimal
import urllib.parse as _up, requests
HEADERS={"User-Agent":UA}
def fetch_extract(title):
    r=requests.get(API, params={"action":"query","prop":"extracts|info","titles":_up.unquote(title),"explaintext":1,"exsectionformat":"plain","inprop":"url|displaytitle","redirects":1,"format":"json"}, headers=HEADERS, timeout=30)
    if r.status_code!=200: return None
    pages=r.json().get("query",{}).get("pages",{})
    for k,p in pages.items():
        if k=="-1" or "missing" in p: return None
        return {"title":p.get("title",title),"extract":p.get("extract",""),"url":p.get("fullurl","")}
    return None

reg_added=0
# reuse from paddock_knowledge_wiki.json if exists
pk_path=WIKI_RAW/"paddock_knowledge_wiki.json"
pk_map={}
if pk_path.exists():
    try:
        pk=json.loads(pk_path.read_text(encoding="utf-8"))
        for x in pk:
            if not x.get("missing"): pk_map[x.get("title","").lower()]=x
    except: pass

for t in reg_titles:
    info=pk_map.get(t.lower().replace("_"," ").lower()) or pk_map.get(t.lower())
    if not info:
        # try fetch short
        time.sleep(0.6)
        info=fetch_extract(t)
        if not info: continue
    extract=info.get("extract","")
    if len(extract)<800: continue
    import re
    paras=[x.strip() for x in re.split(r"\n\n+", extract) if x.strip()]
    title=info.get("title",t)
    url=info.get("url",f"https://en.wikipedia.org/wiki/{t}")
    summary=paras[0][:700] if paras else extract[:700]
    # tiered
    if "2022" in t:
        q="What changed in the 2022 Formula One regulations?"
        a=f"2022 regulations reintroduced ground effect, simplified aerodynamics and introduced the budget cap era cars. {summary} Source: Wikipedia:{title}"
        if add_q(q, a, f"Wikipedia:{title}", "regulation", None): reg_added+=1
    elif "2014" in t:
        q="What changed in the 2014 Formula One engine regulations?"
        a=f"2014 introduced the 1.6L V6 turbo-hybrid power units (ERS). {summary} Source: Wikipedia:{title}"
        if add_q(q, a, f"Wikipedia:{title}", "regulation", None): reg_added+=1
    elif "Budget" in t:
        q="What is the Formula One budget cap?"
        a=f"Budget cap: {summary[:800]} Source: Wikipedia:{title}"
        if add_q(q, a, f"Wikipedia:{title}", "regulation", None): reg_added+=1
    elif "Ground" in t:
        q="What is ground effect in Formula One?"
        a=f"Ground effect: {summary[:800]} Source: Wikipedia:{title}"
        if add_q(q, a, f"Wikipedia:{title}", "regulation", None): reg_added+=1
    else:
        q=f"What is {title} in Formula One?"
        a=f"{title}: {summary[:800]} Source: Wikipedia:{title} ({url})"
        if add_q(q, a, f"Wikipedia:{title}", "regulation", None): reg_added+=1
    # second deep
    if len(paras)>=3:
        if add_q(f"Explain {title} history.", paras[2][:750]+f" (Wikipedia:{title})", f"Wikipedia:{title}", "regulation", None): reg_added+=1

print(f"5. Regulations added {reg_added}")

print(f"Total new {len(new_qa)} → {len(existing)+len(new_qa)}")
# append
with open(qa_path,"a",encoding="utf-8") as f:
    for q in new_qa:
        f.write(json.dumps(q, ensure_ascii=False)+"\n")

# update coverage
import collections, json as jj
all_qa=existing+new_qa
by_type=collections.Counter(q["entity_type"] for q in all_qa)
cov=jj.loads((PROC/"coverage_report.json").read_text(encoding="utf-8")) if (PROC/"coverage_report.json").exists() else {}
cov.update({"qa_pairs":len(all_qa),"qa_by_type":dict(by_type),"expansions":{"qualifying":qual_added,"circuits":circ_added,"h2h":h2h_added,"paraphrase":para_added,"regulations":reg_added}})
(PROC/"coverage_report.json").write_text(jj.dumps(cov, indent=2), encoding="utf-8")
print(by_type)
print(cov)
