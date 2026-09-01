# Training Guide — F1-Dataset

> Point to **one file**: `data/final/qa.jsonl` (5670 pairs). Don't point to folder — `data/` is 136M raw.

## File Map

| Use this | Skip this |
|---|---|
| `data/final/qa.jsonl` (2.2M) — `{question, answer, source, entity_type, season}` | `data/raw/` (104M + 19M wiki) |
| `data/final/qa_chatml.jsonl` (you create, 5670) | `data/processed/races_normalized.jsonl` (11M) — build artifact, not SFT |

`source` = traceability (`Jolpica:2023/1/results` or `Wikipedia:Page`) — keep for eval, drop for train if you want.

## 1. Verify (30s)

```bash
python -c "import collections,json; r=[json.loads(l) for l in open('data/processed/races_normalized.jsonl')]; print(sum(1 for v in collections.Counter((x['race_id'],x['driverId']) for x in r).values() if v>1))"  # 0
wc -l data/final/qa.jsonl  # 5670
head -1 data/final/qa.jsonl | python -m json.tool
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
# also: keep a split
python -c "
import json, random
rows=[json.loads(l) for l in open('data/final/qa_chatml.jsonl')]
random.seed(42); random.shuffle(rows)
n=int(len(rows)*0.9)
open('data/final/train.jsonl','w').write('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows[:n]))
open('data/final/val.jsonl','w').write('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows[n:]))
print(f'train {n} val {len(rows)-n}')
"
# train 5103 / val 567
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
# quick accuracy on val: does answer contain expected winner?
import json
val=[json.loads(l) for l in open('data/final/val.jsonl')]
# run model.generate on val user messages, check substring
```

## Tips

- Don't train on `races_normalized.jsonl` — it's structured rows, not instruction pairs.
- Keep `entity_type` for stratified eval (race_result vs driver_bio vs incident).
- Small dataset (5670) → 3 epochs, lr 2e-4, QLoRA r=16 works; don't overfit.
- License: data CC BY-SA (Jolpica/Wikipedia) — attribute in model card.

## Rebuild

```bash
python pipeline/01_fetch_jolpica_bulk.py  # 19 min
python pipeline/fast_normalize.py         # dedup 25784
python pipeline/03_merge_qa.py            # 5670
```

