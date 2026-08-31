"""
Bulk Jolpica fetch to beat 429 — 76 seasons x 4 calls = 304 requests instead of 4596
Uses 5s politeness per request + 30s+15s*attempt backoff on 429. Resume-cached.
Endpoints: /f1/{season}/results.json , /qualifying.json , /driverStandings.json , /constructorStandings.json
Each returns all races/rounds for that season (Ergast-compatible). Limit=30+offset handling.
"""
import json, time, requests
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://api.jolpi.ca/ergast/f1"
RAW = Path("data/raw/jolpica")
PROC = Path("data/processed")
UA = "F1-Dataset-Pipeline/1.0 (research; contact@example.com)"
HEADERS = {"User-Agent": UA}

session = requests.Session()
retry = Retry(total=2, backoff_factor=1, status_forcelist=[500,502,503,504])
session.mount("https://", HTTPAdapter(max_retries=retry))

def get_json_throttled(url, retries=6):
    for attempt in range(retries):
        r = session.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "60"))
            # Jolpica often returns no Retry-After; use 30s base + exponential
            if wait < 30:
                wait = 30 + attempt*15
            print(f"  429 {url} -> sleep {wait}s (attempt {attempt+1}/{retries})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(0.6)
        return r.json()
    r.raise_for_status()
    return r.json()

def fetch_bulk_season(season, kind):
    """
    kind in results, qualifying, driverStandings, constructorStandings
    Saves to RAW/{season}_{kind}.json
    Returns loaded JSON or None
    """
    out_path = RAW / f"{season}_{kind}.json"
    # Re-fetch if truncated (limit=100 era left 76 BAD files) — detect by total>limit or races vs schedule
    if out_path.exists():
        try:
            d = json.loads(out_path.read_text(encoding="utf-8"))
            if "MRData" in d:
                total = int(d.get("MRData", {}).get("total", 0))
                limit = int(d.get("MRData", {}).get("limit", 0))
                # If limit<500 and total>limit, file is truncated — force refetch. Also standings bulk is season-final only (expected), skip that check.
                if limit >= 500 or (kind in ("driverStandings","constructorStandings")):
                    # standings bulk is 1 list by design — no race count check
                    return d
                # for results/qualifying, if total>limit then truncated
                if total <= limit:
                    return d
                print(f"  REFRESH {season} {kind} (truncated limit={limit} total={total})")
        except:
            pass
    url = f"{BASE}/{season}/{kind}.json?limit=100"
    print(f"  FETCH {season} {kind} ...", end=" ", flush=True)
    try:
        d = get_json_throttled(url)
        total = int(d.get("MRData", {}).get("total", 0))
        actual_limit = int(d.get("MRData", {}).get("limit", 100))
        offset = actual_limit
        while offset < total:
            print(f" (paginated offset {offset}/{total}...) ", end=" ", flush=True)
            d2 = get_json_throttled(f"{BASE}/{season}/{kind}.json?limit=100&offset={offset}")
            if "RaceTable" in d.get("MRData", {}):
                existing = {r["round"]: r for r in d["MRData"]["RaceTable"]["Races"]}
                for r2 in d2.get("MRData", {}).get("RaceTable", {}).get("Races", []):
                    if r2["round"] in existing:
                        seen = {x["Driver"]["driverId"] for x in existing[r2["round"]].get("Results", []) if "Driver" in x}
                        qkey = "Results" if "Results" in r2 else "QualifyingResults"
                        for res in r2.get(qkey, []):
                            did = res.get("Driver", {}).get("driverId")
                            if did and did not in seen:
                                existing[r2["round"]].setdefault(qkey, []).append(res)
                                seen.add(did)
                    else:
                        d["MRData"]["RaceTable"]["Races"].append(r2)
                d["MRData"]["RaceTable"]["Races"].sort(key=lambda x: int(x["round"]))
            elif "StandingsTable" in d.get("MRData", {}):
                d["MRData"]["StandingsTable"]["StandingsLists"].extend(d2.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", []))
            offset += int(d2.get("MRData", {}).get("limit", 100))
        out_path.write_text(json.dumps(d, indent=2), encoding="utf-8")
        races_cnt = len(d.get("MRData", {}).get("RaceTable", {}).get("Races", [])) if "RaceTable" in d.get("MRData", {}) else len(d.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", []))
        print(f"OK total={total} races/lists={races_cnt}")
        return d
    except Exception as e:
        print(f"FAIL {e}")
        return None

def bulk_to_per_race_cache():
    """
    After bulk fetch, expand into per-race files for compatibility with existing pipeline
    and for resume logic (so 01_fetch_jolpica can reuse)
    """
    for season in range(1950, 2026):
        # results
        bulk = RAW / f"{season}_results.json"
        if bulk.exists():
            try:
                d = json.loads(bulk.read_text(encoding="utf-8"))
                races = d.get("MRData", {}).get("RaceTable", {}).get("Races", [])
                for race in races:
                    rnd = int(race.get("round", 0))
                    # create per-race file content matching old shape: Races: [race]
                    per = {"MRData": {"xmlns":"", "series":"f1", "limit":"30", "offset":"0", "total":str(len(races)), "RaceTable": {"season":str(season), "round":str(rnd), "Races":[race]}}}
                    p = RAW / str(season) / f"{rnd:02d}_results.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if not p.exists():
                        p.write_text(json.dumps(per, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"  expand {season} results FAIL {e}")
        # qualifying
        bulk = RAW / f"{season}_qualifying.json"
        if bulk.exists():
            try:
                d = json.loads(bulk.read_text(encoding="utf-8"))
                races = d.get("MRData", {}).get("RaceTable", {}).get("Races", [])
                for race in races:
                    rnd = int(race.get("round", 0))
                    per = {"MRData": {"xmlns":"", "series":"f1", "RaceTable": {"season":str(season), "round":str(rnd), "Races":[race]}}}
                    p = RAW / str(season) / f"{rnd:02d}_qualifying.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if not p.exists():
                        p.write_text(json.dumps(per, indent=2), encoding="utf-8")
            except: pass
        # driverStandings
        bulk = RAW / f"{season}_driverStandings.json"
        if bulk.exists():
            try:
                d = json.loads(bulk.read_text(encoding="utf-8"))
                lists = d.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
                for sl in lists:
                    rnd = int(sl.get("round", 0))
                    per = {"MRData": {"xmlns":"", "series":"f1", "StandingsTable": {"season":str(season), "StandingsLists":[sl]}}}
                    p = RAW / str(season) / f"{rnd:02d}_driverStandings.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if not p.exists():
                        p.write_text(json.dumps(per, indent=2), encoding="utf-8")
            except: pass
        # constructorStandings
        bulk = RAW / f"{season}_constructorStandings.json"
        if bulk.exists():
            try:
                d = json.loads(bulk.read_text(encoding="utf-8"))
                lists = d.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
                for sl in lists:
                    rnd = int(sl.get("round", 0))
                    per = {"MRData": {"xmlns":"", "series":"f1", "StandingsTable": {"season":str(season), "StandingsLists":[sl]}}}
                    p = RAW / str(season) / f"{rnd:02d}_constructorStandings.json"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    if not p.exists():
                        p.write_text(json.dumps(per, indent=2), encoding="utf-8")
            except: pass

if __name__ == "__main__":
    import time as t
    t0 = t.time()
    # Adaptive probe — no fixed 90s wait (bulk just finished, window may be clear)
    for _ in range(3):
        try:
            r = session.get(f"{BASE}/1950.json", headers=HEADERS, timeout=15)
            print(f"Probe {r.status_code} (expect 200)")
            if r.status_code == 200:
                break
            print(f"Probe {r.status_code} throttled, waiting 60s")
            time.sleep(60)
        except Exception as e:
            print(f"Probe fail {e}")
            time.sleep(30)

    kinds = ["results","qualifying","driverStandings","constructorStandings"]
    # Resume: only seasons missing bulk files or incomplete
    seasons = list(range(1950, 2026))
    # Filter to seasons where any bulk missing (to skip 1950-1971 done? But bulk not yet fetched for those)
    # We will fetch all 76 bulk — but skip if all 4 bulks exist and look complete
    remaining = []
    for s in seasons:
        needs = []
        for k in kinds:
            p = RAW / f"{s}_{k}.json"
            if not p.exists():
                needs.append(k)
            elif k in ("results", "qualifying"):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    total = int(d.get("MRData", {}).get("total", 0))
                    limit = int(d.get("MRData", {}).get("limit", 0))
                    races = len(d.get("MRData", {}).get("RaceTable", {}).get("Races", []))
                    # schedule races for this season
                    sched_p = RAW / f"{s}_schedule.json"
                    sched_n = len(json.loads(sched_p.read_text(encoding="utf-8")).get("MRData",{}).get("RaceTable",{}).get("Races",[])) if sched_p.exists() else 0
                    # truncated if races < sched (e.g. 8 vs 16) — limit=100 pagination by rows
                    if sched_n and races < sched_n:
                        needs.append(f"{k}({races}/{sched_n})")
                    elif limit < 500 and total > limit and races < sched_n:
                        needs.append(f"{k}(trunc {limit}/{total})")
                except: needs.append(k)
        if needs:
            remaining.append(s)
    print(f"Bulk fetch needed for {len(remaining)}/{len(seasons)} seasons: {remaining[:10]}... needs sample {[s for s in remaining[:3]]}")
    # Fetch remaining seasons sequentially (3s apart keeps under burst limit)
    done = 0
    for season in remaining:
        for kind in kinds:
            fetch_bulk_season(season, kind)
        done += 1
        if done % 10 == 0:
            print(f"Progress {done}/{len(remaining)} seasons elapsed {t.time()-t0:.0f}s")

    print(f"Bulk fetch done in {t.time()-t0:.0f}s, expanding to per-race cache...")
    bulk_to_per_race_cache()

    # Count
    total_files = sum(1 for _ in RAW.rglob("*.json"))
    print(f"Total files now: {total_files}")
    # Quick file counts by year
    for y in [1970,1971,1972,2023,2024]:
        p = RAW / str(y)
        cnt = len(list(p.glob("*.json"))) if p.exists() else 0
        print(f"  {y}: {cnt} per-race files")
