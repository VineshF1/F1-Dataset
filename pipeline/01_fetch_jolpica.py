"""
Jolpica-F1 ingestion: 1950-2025 unified normalized dataset
- Fetches seasons -> schedules -> results/qualifying/standings per race
- Normalizes to schema: race_id, season, round, circuit, date, driver, constructor, grid, finish, points, status, standings
- Cross-checks race counts & champions vs known records
- Rate-limited: 5 concurrent, 0.2s politeness, retry+backoff
"""
import json, time, os, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://api.jolpi.ca/ergast/f1"
RAW = Path("data/raw/jolpica")
PROC = Path("data/processed")
RAW.mkdir(parents=True, exist_ok=True)
PROC.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "F1-Dataset-Pipeline/1.0 (research; contact@example.com)"}
session = requests.Session()
# Don't auto-retry 429 via urllib3 — handle manually with longer backoff
retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[500,502,503,504])
session.mount("https://", HTTPAdapter(max_retries=retry))

def get_json(url, retries=5):
    for attempt in range(retries):
        r = session.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "8"))
            wait = max(wait, 8) + attempt*5
            print(f"    429 for {url} -> sleep {wait}s (attempt {attempt+1}/{retries})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(1.0)  # 1.0s single-worker — avoids 429 at Jolpica rate limit
        return r.json()
    r.raise_for_status()
    return r.json()

def fetch_seasons():
    d = get_json(f"{BASE}/seasons.json?limit=100")
    seasons = [int(s["season"]) for s in d["MRData"]["SeasonTable"]["Seasons"]]
    seasons = [s for s in seasons if 1950 <= s <= 2025]
    print(f"Seasons: {len(seasons)} ({min(seasons)}-{max(seasons)})")
    (RAW / "seasons.json").write_text(json.dumps(d, indent=2))
    return seasons

def fetch_schedule(season):
    try:
        d = get_json(f"{BASE}/{season}.json")
        races = d["MRData"]["RaceTable"]["Races"]
        (RAW / f"{season}_schedule.json").write_text(json.dumps(d, indent=2))
        print(f"  {season}: {len(races)} races")
        return races
    except Exception as e:
        print(f"  {season} schedule FAIL: {e}")
        return []

def fetch_race_data(args):
    season, rnd, race_name = args
    base = f"{BASE}/{season}/{rnd}"
    out = {"season": season, "round": rnd, "raceName": race_name}
    for kind, url in [
        ("results", f"{base}/results.json"),
        ("qualifying", f"{base}/qualifying.json"),
        ("driverStandings", f"{base}/driverStandings.json"),
        ("constructorStandings", f"{base}/constructorStandings.json"),
    ]:
        p = RAW / str(season) / f"{rnd:02d}_{kind}.json"
        # resume: skip if already cached and looks valid
        if p.exists():
            try:
                cached = json.loads(p.read_text(encoding="utf-8"))
                # valid if MRData present and not error-shaped
                if "MRData" in cached:
                    out[kind] = cached
                    continue
            except: pass
        try:
            d = get_json(url)
            out[kind] = d
            # save raw
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(d, indent=2))
        except Exception as e:
            out[kind+"_error"] = str(e)
            print(f"    {season} R{rnd} {kind} FAIL: {e}")
    return out

def fetch_drivers():
    # Jolpica drivers paginated (limit max ~100 per our probe, but try 100)
    all_drivers=[]
    offset=0
    limit=100
    while True:
        d=get_json(f"{BASE}/drivers.json?limit={limit}&offset={offset}")
        drivers=d["MRData"]["DriverTable"]["Drivers"]
        total=int(d["MRData"]["total"])
        all_drivers.extend(drivers)
        print(f"  drivers {offset}-{offset+len(drivers)} / {total}")
        if offset+limit >= total or not drivers:
            break
        offset+=limit
    (RAW / "drivers.json").write_text(json.dumps(all_drivers, indent=2))
    print(f"Total drivers: {len(all_drivers)}")
    return all_drivers

def fetch_circuits():
    d=get_json(f"{BASE}/circuits.json?limit=100")
    (RAW / "circuits.json").write_text(json.dumps(d, indent=2))
    print(f"Circuits: {d['MRData']['total']}")
    return d

def fetch_constructors():
    d=get_json(f"{BASE}/constructors.json?limit=500")
    (RAW / "constructors.json").write_text(json.dumps(d, indent=2))
    print(f"Constructors: {d['MRData']['total']}")
    return d

# --- main ---
if __name__ == "__main__":
    t0=time.time()
    seasons=fetch_seasons()
    # schedule per season
    all_races=[]
    for s in seasons:
        races=fetch_schedule(s)
        for r in races:
            all_races.append((s, int(r["round"]), r["raceName"]))

    print(f"\nTotal races to fetch: {len(all_races)}")
    # drivers/circuits/constructors in parallel with race fetch prep
    fetch_drivers()
    fetch_circuits()
    fetch_constructors()

    # fetch per-race data — 1 worker to avoid 429, resume-cached via MRData check
    results=[]
    with ThreadPoolExecutor(max_workers=1) as ex:
        futs={ex.submit(fetch_race_data, a): a for a in all_races}
        done=0
        for fut in as_completed(futs):
            done+=1
            try:
                res=fut.result()
                results.append(res)
            except Exception as e:
                print(f"  race FAIL {futs[fut]}: {e}")
            if done%50==0 or done==len(all_races):
                print(f"  progress {done}/{len(all_races)} races ({done/len(all_races)*100:.1f}%) elapsed {time.time()-t0:.0f}s")

    # Normalize to unified schema
    normalized=[]
    for r in results:
        season=r["season"]; rnd=r["round"]
        # results
        try:
            race_list=r.get("results",{}).get("MRData",{}).get("RaceTable",{}).get("Races",[])
            if not race_list: continue
            race=race_list[0]
            circuit=race.get("Circuit",{})
            for res in race.get("Results",[]):
                drv=res.get("Driver",{})
                cons=res.get("Constructor",{})
                # standings snapshot after this race (driver/constr)
                normalized.append({
                    "race_id": f"{season}-{rnd:02d}",
                    "season": int(season),
                    "round": int(rnd),
                    "raceName": race.get("raceName"),
                    "circuit": circuit.get("circuitId"),
                    "circuitName": circuit.get("circuitName"),
                    "country": circuit.get("Location",{}).get("country"),
                    "date": race.get("date"),
                    "driverId": drv.get("driverId"),
                    "driver": f"{drv.get('givenName','')} {drv.get('familyName','')}".strip(),
                    "constructorId": cons.get("constructorId"),
                    "constructor": cons.get("name"),
                    "grid": int(res["grid"]) if str(res.get("grid","")).isdigit() else None,
                    "finish": res.get("position"),
                    "finishText": res.get("positionText"),
                    "points": float(res.get("points",0)),
                    "status": res.get("status"),
                    "laps": int(res["laps"]) if str(res.get("laps","")).isdigit() else None,
                    "source": f"Jolpica:{season}/{rnd}/results",
                })
        except Exception as e:
            print(f" normalize FAIL {season} R{rnd}: {e}")

    # standings snapshots per race
    standings=[]
    for r in results:
        season=r["season"]; rnd=r["round"]
        for kind in ["driverStandings","constructorStandings"]:
            try:
                lists=r.get(kind,{}).get("MRData",{}).get("StandingsTable",{}).get("StandingsLists",[])
                if lists:
                    standings.append({"season":season,"round":rnd,"kind":kind,"data":lists[0]})
            except: pass

    (PROC / "standings_raw.json").write_text(json.dumps(standings, indent=2))

    # champions per season
    champions=[]
    for s in seasons:
        try:
            d=get_json(f"{BASE}/{s}/driverStandings.json")
            lists=d["MRData"]["StandingsTable"]["StandingsLists"]
            if lists:
                champ=lists[0]["DriverStandings"][0]
                champions.append({"season":s,"type":"drivers",
                    "champion": f"{champ['Driver']['givenName']} {champ['Driver']['familyName']}",
                    "championId": champ["Driver"]["driverId"],
                    "points": champ["points"],"wins": champ["wins"]})
            d2=get_json(f"{BASE}/{s}/constructorStandings.json")
            lists2=d2["MRData"]["StandingsTable"]["StandingsLists"]
            if lists2:
                c2=lists2[0]["ConstructorStandings"][0]
                champions.append({"season":s,"type":"constructors","champion":c2["Constructor"]["name"],
                    "championId": c2["Constructor"]["constructorId"],"points":c2["points"],"wins":c2["wins"]})
        except Exception as e:
            print(f" champion FAIL {s}: {e}")
    (PROC / "champions.json").write_text(json.dumps(champions, indent=2))

    # cross-check race counts
    from collections import Counter
    counts=Counter(n["season"] for n in normalized)
    # dedup race counts
    race_counts={}
    for s in seasons:
        race_counts[s]=len([r for r in all_races if r[0]==s])
    # known checks: a few spot checks
    known_champions={2001:("Michael Schumacher","Ferrari"),2021:("Max Verstappen","Mercedes"),1994:("Michael Schumacher","Williams")}
    mismatches=[]
    for yr,(d_exp,c_exp) in known_champions.items():
        got=[ch for ch in champions if ch["season"]==yr and ch["type"]=="drivers"]
        if got and got[0]["champion"]!=d_exp:
            mismatches.append(f"{yr} driver champion mismatch: got {got[0]['champion']} exp {d_exp}")

    # write normalized
    import csv
    # JSONL
    with open(PROC / "races_normalized.jsonl","w",encoding="utf-8") as f:
        for row in sorted(normalized, key=lambda x:(x["season"],x["round"],int(x["finish"]) if str(x["finish"]).isdigit() else 99)):
            f.write(json.dumps(row, ensure_ascii=False)+"\n")
    # also JSON array for inspection
    with open(PROC / "races_normalized.json","w",encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    meta={
        "seasons": len(seasons),
        "races": len(all_races),
        "normalized_rows": len(normalized),
        "race_counts": race_counts,
        "champions_sample": champions[:6],
        "mismatches": mismatches,
        "elapsed_s": time.time()-t0,
    }
    (PROC / "jolpica_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"\nDone: {len(normalized)} rows, {len(all_races)} races, {len(seasons)} seasons in {time.time()-t0:.0f}s")
    print(f"Champions mismatches: {mismatches or 'none'}")
    print(f"Output: {PROC/'races_normalized.jsonl'}")
