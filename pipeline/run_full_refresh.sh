set -e
echo "[1/3] bulk refresh (remaining truncated seasons, 0.6s polite)"
python pipeline/01_fetch_jolpica_bulk.py
echo "[2/3] normalize"
python pipeline/fast_normalize.py
echo "[3/3] qa"
python pipeline/03_merge_qa.py
python -c "
import json
rows=len(open('data/processed/races_normalized.jsonl',encoding='utf-8').readlines())
qa=len(open('data/final/qa.jsonl',encoding='utf-8').readlines())
print(f'DONE rows={rows} qa={qa}')
# coverage
from collections import Counter
r=[json.loads(l) for l in open('data/processed/races_normalized.jsonl',encoding='utf-8')]
races=len(set((x['season'],x['round']) for x in r))
print(f'races {races}/1149 ({races/1149*100:.1f}%)')
"
echo "=== data sizes ==="
du -sh data/final data/processed data 2>&1
ls -lh data/final/qa.jsonl data/processed/races_normalized.jsonl 2>&1
