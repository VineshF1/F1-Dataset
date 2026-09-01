"""B exhaustive — 30 paddock persons + 50 F1 knowledge (basic→advanced)
Appends to data/final/qa.jsonl (5670→~5750), sources Wikipedia:Page
No telemetry/laps/weather stored. 0.15s polite, UA required.
"""
import json, re, time, urllib.parse as _up, pathlib, requests

RAW_WIKI = pathlib.Path("data/raw/wikipedia")
FINAL = pathlib.Path("data/final")
PROC = pathlib.Path("data/processed")
UA = "F1-Dataset-Pipeline/1.0 (research; contact@example.com)"
API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": UA}

PERSON_TITLES = [
    "Christian_Horner","Toto_Wolff","Frédéric_Vasseur","Andrea_Stella","Zak_Brown",
    "Adrian_Newey","Ross_Brawn","Bernie_Ecclestone","Jean_Todt","Flavio_Briatore",
    "Guenther_Steiner","Helmut_Marko","Stefano_Domenicali","Enzo_Ferrari","Frank_Williams",
    "Colin_Chapman","Ron_Dennis","Lawrence_Stroll","James_Vowles","Ayao_Komatsu",
    "Franz_Tost","Otmar_Szafnauer","Mattia_Binotto","Andreas_Seidl","Claire_Williams",
    "Eddie_Jordan","Dietrich_Mateschitz","Luca_di_Montezemolo","Max_Mosley","Mohammed_Ben_Sulayem",
]

KNOWLEDGE_TITLES = [
    # basic sporting
    "Glossary_of_Formula_One_terms","List_of_Formula_One_flags","Formula_One_tyres","Formula_One_Grand_Prix",
    "List_of_Formula_One_circuits","List_of_Formula_One_Grands_Prix","Formula_One_World_Championship",
    # weekend/sporting
    "Formula_One_regulations","History_of_Formula_One_regulations","Parc_fermé","Qualifying","Formula_One_sprint",
    "Safety_car","Virtual_safety_car","Pit_stop","List_of_Formula_One_points_scoring_systems","FIA_Super_Licence",
    # technical
    "Formula_One_engines","Formula_One_aerodynamics","Ground_effect_(cars)","Kinetic_energy_recovery_system",
    "Halo_(motor_sport)","Drag_reduction_system","Formula_One_steering_wheel","Carbon_fiber_in_Formula_One",
    # commercial/governance
    "Concorde_Agreement","Budget_cap","Formula_One_constructors","List_of_Formula_One_constructors","Liberty_Media",
    "Fédération_Internationale_de_l'Automobile","Formula_One_Group",
    # safety/history
    "History_of_Formula_One","History_of_Formula_One_safety","Formula_One_fatalities",
    # engines/tyres evolution
    "Turbocharger","Hybrid_electric_vehicle","Pirelli","Bridgestone",
    # strategy/flags specifics
    "Formula_One_tyres","List_of_Formula_One_flags","Drag_reduction_system","Parc_fermé",
    # extra to reach 50 — deduped later
    "Pole_position","Fastest_lap","Hat-trick_(Formula_One)","Grand_Chelem","Monaco_Grand_Prix",
    "Silverstone_Circuit","Suzuka_International_Racing_Course",
]

# dedup preserving order
def dedup(seq):
    seen=set(); out=[]
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out
KNOWLEDGE_TITLES = dedup(KNOWLEDGE_TITLES)

def wiki_extract(title, retries=5):
    decoded=_up.unquote(title)
    for attempt in range(retries):
        r=requests.get(API, params={"action":"query","prop":"extracts|info","titles":decoded,"explaintext":1,"exsectionformat":"plain","inprop":"url|displaytitle","redirects":1,"format":"json"}, headers=HEADERS, timeout=30)
        if r.status_code==429:
            wait=int(r.headers.get("Retry-After","5"))
            wait=max(wait, 5+attempt*5)
            print(f"  429 {decoded} sleep {wait}s {attempt+1}/{retries}")
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(0.6)
        pages=r.json().get("query",{}).get("pages",{})
        for k,p in pages.items():
            if k=="-1" or "missing" in p or "invalid" in p:
                return {"title":decoded,"missing":True,"extract":"","url":f"https://en.wikipedia.org/wiki/{decoded.replace(' ','_')}"}
            extract=p.get("extract","") or ""
            url=p.get("fullurl") or f"https://en.wikipedia.org/wiki/{decoded.replace(' ','_')}"
            return {"title":p.get("title",decoded),"display":p.get("displaytitle",decoded),"extract":extract,"url":url,"missing":False}
        return {"title":decoded,"missing":True,"extract":"","url":f"https://en.wikipedia.org/wiki/{decoded.replace(' ','_')}"}
    print(f"  FAIL {decoded} after {retries} 429s")
    return {"title":decoded,"missing":True,"extract":"","url":f"https://en.wikipedia.org/wiki/{decoded.replace(' ','_')}"}

def first_paras(extract, n=2, limit=900):
    paras=[x.strip() for x in re.split(r"\n\n+", extract) if x.strip()]
    txt="\n\n".join(paras[:n])
    if len(txt)>limit:
        txt=txt[:limit].rsplit(" ",1)[0]+"..."
    return txt

# fetch
persons=[]
print(f"Fetching {len(PERSON_TITLES)} persons...")
for t in PERSON_TITLES:
    d=wiki_extract(t); d["query_title"]=t
    persons.append(d)
    print(f"  {t} -> {len(d.get('extract',''))} {'MISSING' if d.get('missing') else 'OK'}")

knowledge=[]
print(f"Fetching {len(KNOWLEDGE_TITLES)} knowledge...")
for t in KNOWLEDGE_TITLES:
    d=wiki_extract(t); d["query_title"]=t
    knowledge.append(d)
    print(f"  {t} -> {len(d.get('extract',''))} {'MISSING' if d.get('missing') else 'OK'}")

# stats
persons_ok=[p for p in persons if not p.get("missing") and len(p.get("extract",""))>500]
knowledge_ok=[k for k in knowledge if not k.get("missing") and len(k.get("extract",""))>500]
print(f"Persons OK {len(persons_ok)}/{len(persons)} Knowledge OK {len(knowledge_ok)}/{len(knowledge)}")

# save raw
RAW_WIKI.mkdir(parents=True, exist_ok=True)
(RAW_WIKI/"paddock_persons_wiki.json").write_text(json.dumps(persons, indent=2, ensure_ascii=False), encoding="utf-8")
(RAW_WIKI/"paddock_knowledge_wiki.json").write_text(json.dumps(knowledge, indent=2, ensure_ascii=False), encoding="utf-8")

# load existing qa
qa_path=FINAL/"qa.jsonl"
existing=[]
if qa_path.exists():
    for line in qa_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try: existing.append(json.loads(line))
            except: pass
existing_q=set(q["question"].strip().lower() for q in existing)
print(f"Existing QA {len(existing)}")

def add_qa(qa_list, question, answer, source, entity_type, season=None):
    key=question.strip().lower()
    if key in existing_q: return False
    if not answer or len(answer)<80: return False
    qa_list.append({"question":question,"answer":answer,"source":source,"entity_type":entity_type,"season":season})
    existing_q.add(key)
    return True

new_qa=[]

# Persons → 2-3 QA each
for p in persons_ok:
    name=p["title"]  # display e.g. Christian Horner
    # clean name without disambiguation
    short=re.sub(r"\s*\(.*\)","",name)
    extract=p["extract"]
    summary=first_paras(extract, n=2, limit=900)
    url=p["url"]
    # Q1: Who is X?
    a1=f"{short} — {summary} Source: Wikipedia:{name} ({url})"
    add_qa(new_qa, f"Who is {short}?", a1, f"Wikipedia:{name}", "person", None)
    # Q2: role
    add_qa(new_qa, f"What is {short}'s role in Formula One?", f"{short} is known in Formula One for: {summary[:700]}", f"Wikipedia:{name}", "person", None)
    # Q3: team association (try extract line with team)
    m=re.search(r"(Red Bull|Mercedes|Ferrari|McLaren|Williams|Renault|Alpine|Haas|Aston Martin|Sauber|AlphaTauri|Racing Point|Force India|Lotus|Brawn|Benetton)[^\.]*\.", extract)
    if m:
        add_qa(new_qa, f"Which team is {short} associated with?", f"{short} is associated with {m.group(0).strip()} (Wikipedia:{name}).", f"Wikipedia:{name}", "person", None)

# Knowledge → 1-2 QA each, tiered
for k in knowledge_ok:
    title=k["title"]  # e.g. Drag reduction system
    short=re.sub(r"\s*\(.*\)","",title)
    extract=k["extract"]
    summary=first_paras(extract, n=2, limit=850)
    url=k["url"]
    # basic: What is X?
    q=f"What is {short} in Formula One?"
    a=f"{short} in Formula One: {summary} Source: Wikipedia:{title} ({url})"
    ok=add_qa(new_qa, q, a, f"Wikipedia:{title}", "f1_knowledge", None)
    # advanced second phrasing for longer extracts
    if ok and len(extract)>3000:
        paras=[x.strip() for x in re.split(r"\n\n+", extract) if x.strip()]
        if len(paras)>=3:
            detail=paras[2][:700]
            add_qa(new_qa, f"Explain {short} in F1.", f"{short}: {detail} (Wikipedia:{title})", f"Wikipedia:{title}", "f1_knowledge", None)

print(f"New QA generated {len(new_qa)}")

# append
with open(qa_path, "a", encoding="utf-8") as f:
    for q in new_qa:
        f.write(json.dumps(q, ensure_ascii=False)+"\n")
print(f"Appended. Total now {len(existing)+len(new_qa)}")

# update coverage
import collections
all_qa=existing+new_qa
by_type=collections.Counter(q["entity_type"] for q in all_qa)
print(by_type)
try:
    cov=json.loads((PROC/"coverage_report.json").read_text(encoding="utf-8"))
except: cov={}
cov.update({"qa_pairs":len(all_qa),"qa_by_type":dict(by_type),"paddock_persons":f"{len(persons_ok)}/{len(PERSON_TITLES)}","f1_knowledge":f"{len(knowledge_ok)}/{len(KNOWLEDGE_TITLES)}","note_paddock":"B exhaustive 30 persons + 50 knowledge"})
(PROC/"coverage_report.json").write_text(json.dumps(cov, indent=2), encoding="utf-8")
print("coverage updated", cov)
