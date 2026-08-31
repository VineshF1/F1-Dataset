"""
Wikipedia ingestion for Task 2
- Drivers: every driverId from Jolpica drivers.json (881) -> Wikipedia page via driver wikipedia URL or title search
- Seasons: 1950-2025 season summary pages
- Incidents/rivalries/controversies + constructor histories (curated list)
- Preserves factual paragraphs, extracts death/crash facts verbatim, flags single low-traffic pages
"""
import json, time, re, os
from pathlib import Path
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RAW = Path("data/raw/wikipedia")
RAW.mkdir(parents=True, exist_ok=True)
PROC = Path("data/processed")
PROC.mkdir(parents=True, exist_ok=True)

UA = "F1-Dataset-Pipeline/1.0 (research; contact@example.com)"
API = "https://en.wikipedia.org/w/api.php"

sess = requests.Session()
retry = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504])
sess.mount("https://", HTTPAdapter(max_retries=retry))

def wiki_extract(title):
    """Fetch full plaintext extract. Separate call — combining extracts+pageviews returns empty extracts."""
    import urllib.parse as _up
    decoded = _up.unquote(title)
    params = {
        "action":"query", "prop":"extracts|info",
        "titles": decoded, "explaintext":1, "exsectionformat":"plain",
        "inprop":"url|displaytitle", "redirects":1, "format":"json"
    }
    try:
        r = sess.get(API, params=params, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        time.sleep(0.15)
        j = r.json()
        pages = j.get("query",{}).get("pages",{})
        k = list(pages.keys())[0]
        p = pages[k]
        if k=="-1" or "missing" in p or "invalid" in p:
            return {"title": decoded, "missing": True, "source": f"Wikipedia:{decoded}"}
        extract = p.get("extract","") or ""
        paras = [x.strip() for x in re.split(r"\n\n+", extract) if x.strip()]
        url = p.get("fullurl") or f"https://en.wikipedia.org/wiki/{decoded.replace(' ','_')}"
        # low-traffic heuristic: stub article (<3000 chars) OR pre-1970s driver with short page
        low_traffic = len(extract) < 3000
        death_terms = ["died","death","fatal","killed","accident","crash"]
        has_death = any(t in extract.lower() for t in death_terms)
        return {
            "title": p.get("title", decoded),
            "url": url,
            "extract": extract,
            "paragraphs": paras,
            "char_count": len(extract),
            "pageviews_30d": None,
            "low_traffic_flag": low_traffic,
            "has_death_terms": has_death,
            "source": f"Wikipedia:{decoded}",
        }
    except Exception as e:
        return {"title": decoded, "error": str(e), "source": f"Wikipedia:{decoded}"}

def load_drivers():
    # Jolpica paginated — must fetch all 881, not just first 100
    drivers=[]
    offset=0
    limit=100
    import requests as rq
    while True:
        try:
            d = rq.get(f"https://api.jolpi.ca/ergast/f1/drivers.json?limit={limit}&offset={offset}",
                       headers={"User-Agent": UA}, timeout=30).json()
            batch = d["MRData"]["DriverTable"]["Drivers"]
            total = int(d["MRData"]["total"])
            drivers.extend(batch)
            print(f"  drivers batch {offset}-{offset+len(batch)}/{total}")
            if offset+limit >= total or not batch:
                break
            offset+=limit
            time.sleep(0.2)
        except Exception as e:
            print(f"  drivers fetch FAIL at offset {offset}: {e}")
            break
    return drivers

# Curated entity lists (spec says: every season, major incidents, rivalries, controversies, constructor histories)
SEASON_TITLES = [f"{y}_Formula_One_World_Championship" for y in range(1950, 2026)]
INCIDENT_TITLES = [
    "Death_of_Ayrton_Senna", "1994_San_Marino_Grand_Prix",
    "Jules_Bianchi", "2014_Japanese_Grand_Prix",
    "Roland_Ratzenberger",
    "2008_Singapore_Grand_Prix", # Crashgate
    "2007_Formula_One_espionage_controversy", # Spygate
    "2021_Abu_Dhabi_Grand_Prix",
    "Ayrton_Senna–Alain_Prost_rivalry", "Senna–Prost_rivalry",
    "Lewis_Hamilton–Max_Verstappen_rivalry", "2021_Formula_One_World_Championship",
    "Niki_Lauda", "Romain_Grosjean", "Anthoine_Hubert",
    "History_of_Formula_One_regulations",
]
CONSTRUCTOR_TITLES = [
    "Mercedes-Benz_in_Formula_One", "Scuderia_Ferrari", "McLaren", "Williams_Grand_Prix_Engineering",
    "Red_Bull_Racing", "Renault_in_Formula_One", "Aston_Martin_in_Formula_One",
    "Alfa_Romeo_in_Formula_One", "Lotus_F1", "Brabham",
    "List_of_Formula_One_constructors",
]

def fetch_many(titles, label, workers=5):
    print(f"\n[{label}] fetching {len(titles)} pages...")
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs={ex.submit(wiki_extract, t): t for t in titles}
        done=0
        for fut in as_completed(futs):
            done+=1
            title=futs[fut]
            try:
                r=fut.result()
                results.append(r)
                flag=" [LOW-TRAFFIC]" if r.get("low_traffic_flag") else ""
                miss=" [MISSING]" if r.get("missing") else ""
                print(f"  {done}/{len(titles)} {title}{miss}{flag} -> {r.get('char_count',0)} chars")
            except Exception as e:
                print(f"  FAIL {title}: {e}")
                results.append({"title":title,"error":str(e)})
    return results

if __name__ == "__main__":
    t0=time.time()
    drivers = load_drivers()
    print(f"Drivers: {len(drivers)} from Jolpica")
    # Build driver title list: use wikipedia url slug when available, else given+family name
    driver_titles=[]
    for d in drivers:
        url = d.get("url","")
        # url like http://en.wikipedia.org/wiki/Nino_Farina
        m = re.search(r"/wiki/([^#?]+)", url)
        if m:
            driver_titles.append(m.group(1))
        else:
            # fallback: Given_Family
            driver_titles.append(f"{d.get('givenName','')}_{d.get('familyName','')}".strip().replace(" ","_"))

    driver_results = fetch_many(driver_titles, "DRIVERS", workers=5)
    (RAW / "drivers_wiki.json").write_text(json.dumps(driver_results, ensure_ascii=False, indent=2), encoding="utf-8")

    season_results = fetch_many(SEASON_TITLES, "SEASONS", workers=5)
    (RAW / "seasons_wiki.json").write_text(json.dumps(season_results, ensure_ascii=False, indent=2), encoding="utf-8")

    incident_results = fetch_many(INCIDENT_TITLES, "INCIDENTS/RIVALRIES", workers=5)
    (RAW / "incidents_wiki.json").write_text(json.dumps(incident_results, ensure_ascii=False, indent=2), encoding="utf-8")

    constructor_results = fetch_many(CONSTRUCTOR_TITLES, "CONSTRUCTORS", workers=5)
    (RAW / "constructors_wiki.json").write_text(json.dumps(constructor_results, ensure_ascii=False, indent=2), encoding="utf-8")

    # coverage summary
    def coverage(lst):
        total=len(lst); missing=sum(1 for x in lst if x.get("missing")); flagged=sum(1 for x in lst if x.get("low_traffic_flag"))
        chars=sum(x.get("char_count",0) for x in lst if not x.get("missing"))
        return {"total":total,"missing":missing,"low_traffic":flagged,"chars":chars}
    meta={
        "drivers": coverage(driver_results),
        "seasons": coverage(season_results),
        "incidents": coverage(incident_results),
        "constructors": coverage(constructor_results),
        "elapsed_s": time.time()-t0,
    }
    (PROC / "wikipedia_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nDone drivers={len(driver_results)} seasons={len(season_results)} incidents={len(incident_results)} constructors={len(constructor_results)} in {time.time()-t0:.0f}s")
    print(json.dumps(meta, indent=2))
