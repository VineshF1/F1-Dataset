"""Fast normalize: merge bulk + per-race cache -> races_normalized.jsonl + champions.json
No API calls — uses existing data/raw/jolpica only. Deduplicates by race_id+driverId.
"""
import json
from pathlib import Path
from collections import defaultdict, Counter

RAW = Path("data/raw/jolpica")
PROC = Path("data/processed")
PROC.mkdir(parents=True, exist_ok=True)

seasons = list(range(1950, 2026))
races_by_key = {}  # (season, round) -> race dict with Results

for s in seasons:
    # 1. bulk results
    bulk = RAW / f"{s}_results.json"
    if bulk.exists():
        try:
            d = json.loads(bulk.read_text(encoding="utf-8"))
            for race in d.get("MRData", {}).get("RaceTable", {}).get("Races", []):
                k = (int(s), int(race.get("round", 0)))
                if k not in races_by_key:
                    races_by_key[k] = race
                else:
                    # merge Results dedup by driverId
                    existing = races_by_key[k]
                    seen = {r.get("Driver",{}).get("driverId") for r in existing.get("Results",[])}
                    for res in race.get("Results",[]):
                        did = res.get("Driver",{}).get("driverId")
                        if did not in seen:
                            existing.setdefault("Results", []).append(res)
        except Exception as e:
            print(f"bulk {s} fail {e}")
    # 2. per-race dir supplement (covers pre-bulk complete seasons like 1970)
    pdir = RAW / str(s)
    if pdir.exists():
        for p in pdir.glob("*_results.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                races = d.get("MRData",{}).get("RaceTable",{}).get("Races",[]) or []
                if not races: continue
                race = races[0]
                k = (int(s), int(race.get("round", 0)))
                if k not in races_by_key:
                    races_by_key[k] = race
                else:
                    seen = {r.get("Driver",{}).get("driverId") for r in races_by_key[k].get("Results",[])}
                    for res in race.get("Results",[]):
                        did = res.get("Driver",{}).get("driverId")
                        if did not in seen:
                            races_by_key[k].setdefault("Results", []).append(res)
            except: pass

print(f"Merged races: {len(races_by_key)} (schedule 1149 expected)")

# Normalize to schema
normalized = []
for (season, rnd), race in races_by_key.items():
    circuit = race.get("Circuit", {})
    for res in race.get("Results", []):
        drv = res.get("Driver", {})
        cons = res.get("Constructor", {})
        normalized.append({
            "race_id": f"{season}-{rnd:02d}",
            "season": int(season),
            "round": int(rnd),
            "raceName": race.get("raceName"),
            "circuit": circuit.get("circuitId"),
            "circuitName": circuit.get("circuitName"),
            "country": circuit.get("Location", {}).get("country"),
            "date": race.get("date"),
            "driverId": drv.get("driverId"),
            "driver": f"{drv.get('givenName','')} {drv.get('familyName','')}".strip(),
            "constructorId": cons.get("constructorId"),
            "constructor": cons.get("name"),
            "grid": int(res["grid"]) if str(res.get("grid","")).isdigit() else None,
            "finish": res.get("position"),
            "finishText": res.get("positionText"),
            "points": float(res.get("points", 0)),
            "status": res.get("status"),
            "laps": int(res["laps"]) if str(res.get("laps","")).isdigit() else None,
            "source": f"Jolpica:{season}/{rnd}/results",
        })

# Sort + write JSONL
normalized.sort(key=lambda x: (x["season"], x["round"], int(x["finish"]) if str(x["finish"]).isdigit() else 99))
with open(PROC / "races_normalized.jsonl", "w", encoding="utf-8") as f:
    for row in normalized:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
with open(PROC / "races_normalized.json", "w", encoding="utf-8") as f:
    json.dump(normalized, f, indent=2, ensure_ascii=False)

# Champions from bulk standings (season-final)
champions = []
for s in seasons:
    try:
        p = RAW / f"{s}_driverStandings.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            lists = d.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
            if lists:
                champ = lists[0]["DriverStandings"][0]
                champions.append({"season": s, "type": "drivers", "champion": f"{champ['Driver']['givenName']} {champ['Driver']['familyName']}", "championId": champ["Driver"]["driverId"], "points": champ["points"], "wins": champ["wins"], "source": f"Jolpica:{s}/driverStandings"})
        p2 = RAW / f"{s}_constructorStandings.json"
        if p2.exists():
            d2 = json.loads(p2.read_text(encoding="utf-8"))
            lists2 = d2.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
            if lists2:
                c2 = lists2[0]["ConstructorStandings"][0]
                champions.append({"season": s, "type": "constructors", "champion": c2["Constructor"]["name"], "championId": c2["Constructor"]["constructorId"], "points": c2["points"], "wins": c2["wins"], "source": f"Jolpica:{s}/constructorStandings"})
    except Exception as e:
        print(f"champion {s} fail {e}")

(PROC / "champions.json").write_text(json.dumps(champions, indent=2, ensure_ascii=False))

# standings_raw per race (from per-race dirs if exist)
standings = []
for s in seasons:
    pdir = RAW / str(s)
    if not pdir.exists(): continue
    for p in pdir.glob("*_driverStandings.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            lists = d.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
            if lists:
                rnd = int(p.name.split("_")[0])
                standings.append({"season": s, "round": rnd, "kind": "driverStandings", "data": lists[0]})
        except: pass
    for p in pdir.glob("*_constructorStandings.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            lists = d.get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
            if lists:
                rnd = int(p.name.split("_")[0])
                standings.append({"season": s, "round": rnd, "kind": "constructorStandings", "data": lists[0]})
        except: pass
(PROC / "standings_raw.json").write_text(json.dumps(standings, indent=2))

# meta
race_counts = Counter(n["season"] for n in normalized)
uniq_races = len(races_by_key)
meta = {"seasons": 76, "races_merged": uniq_races, "normalized_rows": len(normalized), "champions": len(champions), "race_counts_sample": {k: race_counts[k] for k in sorted(race_counts)[:5]}}
(PROC / "jolpica_meta.json").write_text(json.dumps(meta, indent=2))
print(f"Done: {len(normalized)} rows, {uniq_races} races, {len(champions)} champions")
print(meta)
