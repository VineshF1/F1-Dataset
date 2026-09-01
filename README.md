# F1-Dataset 1950-2025

LLM Q&A finetuning dataset — 1149 races, 25,784 results, 10418 QA pairs.

## Sources
- **Jolpica F1 API** (`api.jolpi.ca/ergast/f1`) — 76 seasons bulk `/{season}/{results,qualifying,driverStandings,constructorStandings}.json` (CC BY-SA)
- **Wikipedia** (`wikipedia-api`) — 881 drivers, 76 seasons, 16 incidents, 11 constructors + 30 paddock persons + 38 F1 knowledge + 78 circuits

## Data
```
data/raw/jolpica/          76 bulk _results.json + _schedule.json (104M)
data/raw/wikipedia/        drivers_wiki.json (14M) seasons_wiki.json (4.1M) paddock_*.json (1.4M)
data/processed/races_normalized.jsonl  25,784 rows, 1149 races
data/processed/champions.json          144 (76 drivers + 68 constructors)
data/final/qa.jsonl                    10418 pairs {question,answer,source,entity_type,season}
```
QA: `5745` race_result · `2039` qualifying · `1748` driver_bio · `364` champion · `177` circuit · `83` person · `80` season · `63` f1_knowledge · `80` h2h · `31` incident · `8` regulation

## QA schema
`question` paraphrased (3x→5x per race), `answer` factual, `source` traceable `Jolpica:season/round/results` or `Jolpica:season/round/qualifying` or `Wikipedia:Page`, `entity_type` race_result|qualifying|season_champion|driver_bio|person|f1_knowledge|circuit|h2h|incident|regulation, `season` int.

## Architecture

```mermaid
flowchart TB
    subgraph SOURCES["Sources"]
        A["<b>Jolpica Bulk</b><br/>76 seasons · 1149 races"]
        B["<b>Wikipedia Core</b><br/>881 drivers · 76 seasons"]
        C["<b>Paddock</b><br/>30 persons · Horner/Wolff/Newey"]
        D["<b>F1 Knowledge</b><br/>38 terms · DRS/Parc fermé/PU"]
    end

    subgraph PIPELINE["Pipeline"]
        E["<b>fast_normalize.py</b><br/>25,784 rows · dedup"]
        F["<b>06_expand_dataset.py</b><br/>qual + circuits + h2h + 5×"]
    end

    subgraph OUTPUT["Dataset"]
        G["<b>races_normalized.jsonl</b><br/>11 MB"]
        H["<b>qa.jsonl</b><br/>10418 pairs · 3.5 MB"]
        I["<b>champions.json</b><br/>144"]
    end

    A --> E
    E --> F
    B --> F
    C --> F
    D --> F
    F --> G
    F --> H
    F --> I

    style A fill:#DC0000,stroke:#FF6B6B,stroke-width:2px,color:#fff
    style B fill:#005AFF,stroke:#60A5FA,stroke-width:2px,color:#fff
    style C fill:#00665E,stroke:#2DD4BF,stroke-width:2px,color:#fff
    style D fill:#FF8000,stroke:#FDBA74,stroke-width:2px,color:#fff
    style E fill:#1E3A8A,stroke:#60A5FA,stroke-width:2px,color:#fff
    style F fill:#7C3AED,stroke:#C4B5FD,stroke-width:2px,color:#fff
    style G fill:#0E7490,stroke:#22D3EE,stroke-width:2px,color:#fff
    style H fill:#BE123C,stroke:#FDA4AF,stroke-width:2px,color:#fff
    style I fill:#4338CA,stroke:#A5B4FC,stroke-width:2px,color:#fff

    style SOURCES fill:#1e1e2e,stroke:#6b7280,stroke-width:1px,color:#d1d5db
    style PIPELINE fill:#1e1e2e,stroke:#6b7280,stroke-width:1px,color:#d1d5db
    style OUTPUT fill:#1e1e2e,stroke:#6b7280,stroke-width:1px,color:#d1d5db
```

## Usage
```python
from datasets import load_dataset
ds = load_dataset("json", data_files="data/final/qa.jsonl")  # 10418
```

## Reproduce
```bash
pip install requests wikipedia-api
python pipeline/01_fetch_jolpica_bulk.py  # 0.6s polite, offset+=100 paginated, races==sched
python pipeline/fast_normalize.py         # dedup (race_id,driverId) → 25784
python pipeline/02_fetch_wikipedia.py     # 881 drivers + 76 seasons
python pipeline/05_add_paddock_knowledge.py  # 30 persons + 38 knowledge → 5816
python pipeline/06_expand_dataset.py      # qual 2039 + circuits 177 + h2h 80 + 5× 2298 + regs 8 → 10418
```

## Coverage
1950-2025 **100% races (1149/1149)**, 76/76 seasons, 881/881 drivers, 78/78 circuits, 30/30 paddock, 38/46 knowledge, qualifying from 1996 onward (pre-1996 no qual data). FastF1 cross-check deferred (results only, no telemetry/laps/weather).

## License
Data CC BY-SA 4.0 (Jolpica/Wikipedia), code MIT. See `data/processed/DATA_DICTIONARY.json`.

## Author

**Vinesh**

Built with ❤️
