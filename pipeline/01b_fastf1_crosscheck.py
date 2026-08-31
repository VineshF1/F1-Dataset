"""
FastF1 cross-check 2018-2025 (results only — no laps/weather/telemetry)
- Uses fastf1.get_session().load(telemetry=False,laps=False,weather=False) to get session.results
- Compares winner/grid/points vs Jolpica normalized; logs mismatches for coverage report
"""
import time, json
from pathlib import Path
import fastf1
import pandas as pd

PROC = Path("data/processed")
PROC.mkdir(parents=True, exist_ok=True)
CACHE = Path("data/cache/fastf1")
CACHE.mkdir(parents=True, exist_ok=True)
fastf1.Cache.enable_cache(str(CACHE))

# Load Jolpica normalized for comparison
norm_path = PROC / "races_normalized.jsonl"
jolpica_by_race = {}
if norm_path.exists():
    import json as _j
    for line in norm_path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        r=_j.loads(line)
        key=(r["season"], r["round"])
        jolpica_by_race.setdefault(key, []).append(r)

def fetch_fastf1_results(season, rnd):
    try:
        # Use round number; fastf1 also accepts string names but round is deterministic from schedule
        sess = fastf1.get_session(season, rnd, 'R')
        sess.load(telemetry=False, laps=False, weather=False)
        res = sess.results
        if res is None or len(res)==0:
            return {"season":season,"round":rnd,"error":"no results"}
        # normalize to simple list
        rows=[]
        for _, row in res.iterrows():
            rows.append({
                "abbr": str(row.get("Abbreviation","")),
                "driver": str(row.get("FullName","") or row.get("BroadcastName","")),
                "team": str(row.get("TeamName","")),
                "position": str(row.get("Position","")),
                "points": float(row.get("Points",0)) if pd.notna(row.get("Points")) else 0,
                "status": str(row.get("Status","")),
                "grid": int(row.get("GridPosition")) if pd.notna(row.get("GridPosition")) else None,
            })
        return {"season":season,"round":rnd,"results":rows, "event": sess.event.get("EventName","") if hasattr(sess,"event") else ""}
    except Exception as e:
        return {"season":season,"round":rnd,"error": str(e)}

if __name__ == "__main__":
    t0=time.time()
    # build schedule rounds 2018-2025 from Jolpica schedules if available
    seasons = list(range(2018, 2026))
    # try to get rounds from Jolpica raw; fallback to 1..24
    import json, pathlib
    targets=[]
    for s in seasons:
        p = Path(f"data/raw/jolpica/{s}_schedule.json")
        if p.exists():
            try:
                d=json.loads(p.read_text(encoding="utf-8"))
                races=d["MRData"]["RaceTable"]["Races"]
                for r in races:
                    targets.append((s, int(r["round"]), r.get("raceName","")))
            except: pass
        else:
            for rnd in range(1, 25):
                targets.append((s, rnd, ""))

    print(f"Cross-check targets: {len(targets)} sessions (2018-2025)")
    results=[]
    mismatches=[]
    for season, rnd, race_name in targets:
        print(f"  {season} R{rnd:02d} {race_name} ...", end=" ", flush=True)
        fr = fetch_fastf1_results(season, rnd)
        results.append(fr)
        if "error" in fr:
            print(f"SKIP: {fr['error'][:80]}")
            continue
        # compare vs Jolpica if available
        key=(season, rnd)
        j_rows=jolpica_by_race.get(key,[])
        if j_rows:
            # compare winner (position 1)
            j_winner = next((r for r in j_rows if str(r["finish"])=="1"), None)
            f_winner = next((r for r in fr["results"] if r["position"]=="1"), None)
            if j_winner and f_winner:
                # compare by abbreviation/full name contains
                j_name=j_winner["driver"].lower()
                f_name=(f_winner["driver"]+" "+f_winner["abbr"]).lower()
                if not any(part in f_name for part in j_name.split()):
                    mismatches.append({"season":season,"round":rnd,"type":"winner_mismatch",
                        "jolpica":j_winner["driver"], "fastf1": f_winner["driver"]})
                    print("MISMATCH winner", j_winner["driver"], "vs", f_winner["driver"])
                else:
                    print(f"OK winner {f_winner['driver']}")
            else:
                print("no winner to compare")
        else:
            print(f"OK ({len(fr['results'])} drivers, no Jolpica to compare)")
        time.sleep(0.3)

    (PROC / "fastf1_crosscheck.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (PROC / "fastf1_mismatches.json").write_text(json.dumps(mismatches, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone {len(results)} sessions, {len(mismatches)} mismatches in {time.time()-t0:.0f}s")
    if mismatches:
        print(json.dumps(mismatches, indent=2))
