# Training Guide — F1-Dataset

> Point to **one file**: `data/final/qa.jsonl` (10418 pairs). Don't point to folder — `data/` is 139M raw.

## File Map

| Use this | Skip this |
|---|---|
| `data/final/qa.jsonl` (3.5M) — `{question, answer, source, entity_type, season}` | `data/raw/` (104M + 19M wiki) |
| `data/final/qa_chatml.jsonl` (you create, 10418) | `data/processed/races_normalized.jsonl` (11M) — build artifact, not SFT |

`source` = traceability (`Jolpica:2023/1/results`, `Jolpica:2023/1/qualifying`, `Wikipedia:Page`) — keep for eval, drop for train if you want.

## 1. Verify (30s)

```bash
python -c "import collections,json; r=[json.loads(l) for l in open('data/processed/races_normalized.jsonl')]; print(sum(1 for v in collections.Counter((x['race_id'],x['driverId']) for x in r).values() if v>1))"  # 0
wc -l data/final/qa.jsonl  # 10418
head -1 data/final/qa.jsonl | python -m json.tool
python -c "import json,collections; print(collections.Counter(q['entity_type'] for q in [json.loads(l) for l in open('data/final/qa.jsonl')]))"
# race_result 5745, qualifying 2039, driver_bio 1748, champion 364, circuit 177, person 83, h2h 80, f1_knowledge 63, incident 31, regulation 8
```

## 2. Convert to ChatML

Trainers want `messages`, not `question/answer`.

```bash
python -c "
import json
out=[]
for l in open('data/final/qa.jsonl',encoding='utf-8'):
    j=json.loads(l)
    out.append({'messages':[{'role':'user','content':j['question']},{'role':'assistant','content':j['answer']}],'source':j['source'],'entity_type':j['entity_type'],'season':j['season']})
open('data/final/qa_chatml.jsonl','w',encoding='utf-8').write('\n'.join(json.dumps(x,ensure_ascii=False) for x in out))
print(len(out))
"
# also: keep a split (90/10)
python -c "
import json, random
rows=[json.loads(l) for l in open('data/final/qa_chatml.jsonl')]
random.seed(42); random.shuffle(rows)
n=int(len(rows)*0.9)
open('data/final/train.jsonl','w').write('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows[:n]))
open('data/final/val.jsonl','w').write('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows[n:]))
print(f'train {n} val {len(rows)-n}')
"
# train 9376 / val 1042 (from 10418)
```

## 3. Train — pick one

**A. Local QLoRA (HF + TRL) — recommended**

```python
from datasets import load_dataset
from trl import SFTTrainer
from transformers import AutoModelForCausalLM, AutoTokenizer

ds = load_dataset("json", data_files={"train":"data/final/train.jsonl","validation":"data/final/val.jsonl"})
model = AutoModelForCausalLM.from_pretrained("meta-llama/Meta-Llama-3.1-8B", load_in_4bit=True, device_map="auto")
tok = AutoTokenizer.from_pretrained("meta-llama/Meta-Llama-3.1-8B")
tok.pad_token = tok.eos_token

trainer = SFTTrainer(model, tok, train_dataset=ds["train"], eval_dataset=ds["validation"], dataset_text_field="messages", max_seq_length=2048)
trainer.train()
```

**B. LLaMA-Factory / Unsloth / Axolotl**

```bash
# LLaMA-Factory: add to dataset_info.json
# "f1_qa": {"file_name": "data/final/train.jsonl", "formatting": "sharegpt"}

# Axolotl
# datasets: [{path: data/final/train.jsonl, type: chat_template, field_messages: messages}]
```

**C. API (OpenAI / Together)**

```bash
openai files create --file data/final/qa_chatml.jsonl --purpose fine-tune
# then: openai fine_tuning.jobs.create --training_file <id> --model gpt-4o-mini-2024-07-18
```

## 4. Push to Hub (optional, for HF AutoTrain)

```bash
huggingface-cli upload Vinesh/f1-qa data/final/qa.jsonl
# then: load_dataset("Vinesh/f1-qa")
```

## 5. Eval

```python
# quick accuracy on val: does answer contain expected winner/pole?
import json
val=[json.loads(l) for l in open('data/final/val.jsonl')]
# run model.generate on val user messages, check substring
# stratify by entity_type: qualifying, race_result, h2h, circuit
```

## Tips

- Don't train on `races_normalized.jsonl` — it's structured rows, not instruction pairs.
- Keep `entity_type` for stratified eval (qualifying vs race_result vs h2h vs circuit).
- 10418 pairs → 3 epochs, lr 2e-4, QLoRA r=16 works; 5816 was v1, 10418 is v2 (+qual 2039 + circuits 177 + h2h 80 + paraphrase 2298 + regs 8).
- Qualifying only from ~1996 onward (pre-1996 no qual data). Filter `entity_type != qualifying` if you want pre-1996 eval.
- License: data CC BY-SA (Jolpica/Wikipedia) — attribute in model card.

## Rebuild

```bash
pip install requests wikipedia-api
python pipeline/01_fetch_jolpica_bulk.py  # 19 min, 104M raw, offset+=100 paginated
python pipeline/fast_normalize.py         # dedup 25784
python pipeline/02_fetch_wikipedia.py     # 881 drivers + 76 seasons
python pipeline/05_add_paddock_knowledge.py  # 30 persons + 38 knowledge → 5816
python pipeline/06_expand_dataset.py      # qual 2039 + circuits 177 + h2h 80 + 5× 2298 + regs 8 → 10418
```
