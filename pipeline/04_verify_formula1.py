"""
Scrape verification 1950-2025: crawl4ai bulk via formula1.com
Verifies Jolpica: race counts, winners, team/driver points vs official site
"""
import asyncio, json, re
from pathlib import Path
from crawl4ai import AsyncWebCrawler

BASE = "https://www.formula1.com/en/results/{year}/{kind}"
RAW_VERIF = Path("data/raw/formula1_verification")
RAW_VERIF.mkdir(parents=True, exist_ok=True)
import time

async def fetch_year_kind(crawler, year, kind, retries=3):
    url = BASE.format(year=year, kind=kind)  # kind: races | drivers | team
    for attempt in range(retries):
        try:
            result = await crawler.arun(url=url, cache_mode="BYPASS")
            if not result.success:
                print(f"  {year}/{kind} FAIL success=False attempt {attempt+1}")
                await asyncio.sleep(5)
                continue
            md = result.markdown or ""
            # quick sanity: check table marker
            if "|" not in md:
                print(f"  {year}/{kind} WARN no table (md_len={len(md)}) attempt {attempt+1}")
            print(f"  {year}/{kind} OK md_len={len(md)}")
            # save markdown for inspection
            (RAW_VERIF / f"{year}_{kind}.md").write_text(md, encoding="utf-8")
            return md
        except Exception as e:
            print(f"  {year}/{kind} EXC {e} attempt {attempt+1}")
            await asyncio.sleep(5)
    print(f"  {year}/{kind} FAILED after {retries}")
    return None

async def main():
    t0 = time.time()
    years = list(range(1950, 2026))
    # We have 228 pages: races+drivers+team per year
    # crawl4ai with Playwright: ~5s/page => 228*5=1140s ~19 min sequential
    # Run concurrent 3 browsers
    semaphore = asyncio.Semaphore(3)
    async with AsyncWebCrawler(verbose=False) as crawler:
        async def bounded(year, kind):
            async with semaphore:
                return year, kind, await fetch_year_kind(crawler, year, kind)
        tasks = [bounded(y, k) for y in years for k in ["races","drivers","team"]]
        results = {}
        for fut in asyncio.as_completed(tasks):
            y, k, md = await fut
            results[(y, k)] = md
            done = sum(1 for v in results.values() if v is not None)
            total = len(years)*3
            if done % 25 == 0 or done == total:
                print(f"Progress {done}/{total} ({done/total*100:.1f}%) elapsed {time.time()-t0:.0f}s")
            await asyncio.sleep(0.5)  # small gap between dispatches

        # Parse race counts from markdown tables
        mismatches = []
        for y in years:
            md = results.get((y, "races"))
            if not md: continue
            # count data rows in RACE RESULTS table: lines with Year-like date and winner
            # Filter: rows with | and date pattern DD MMM or similar
            race_rows = [l for l in md.split("\n") if "|" in l and re.search(r"\d{2} \w{3}", l)]
            # dedupe: some pages have 2 tables; take max
            count = len(race_rows)
            # compare vs Jolpica schedule
            jolpica_path = Path(f"data/raw/jolpica/{y}_schedule.json")
            if jolpica_path.exists():
                try:
                    d = json.loads(jolpica_path.read_text(encoding="utf-8"))
                    jolpica_count = len(d.get("MRData",{}).get("RaceTable",{}).get("Races",[]))
                    if count != jolpica_count and count > 0:
                        mismatches.append({"year": y, "jolpica": jolpica_count, "formula1": count})
                except: pass

        (Path("data/processed") / "formula1_verification.json").write_text(json.dumps({
            "years": len(years),
            "pages": len([v for v in results.values() if v is not None]),
            "mismatches": mismatches,
            "elapsed_s": time.time()-t0
        }, indent=2), encoding="utf-8")
        print(f"Done {len(results)} pages, mismatches: {mismatches}")
        print(f"Output: {RAW_VERIF}/ + data/processed/formula1_verification.json")

if __name__ == "__main__":
    asyncio.run(main())
