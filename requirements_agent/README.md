# Requirements agent

Turns a robotics / physical-AI problem into Catalog-valid JSON. Two LLM steps: (1) infer hardware + paired software even if the user never named a camera or arm, (2) fill one `RequirementsChecklist` per hardware item with complete attributes. Field names match Catalog scoring (`config.CANONICAL_FIELDS`). No vendor search.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # or keep the key in api.yaml
```

## Generate

```bash
python generate.py --problem "3D vision bin picking from a tote into a fixture."
python generate.py --problem-file eval/cases/warehouse_pick.md --out spec.json
python generate.py --spec spec.json --refine "Freezer at -20 C, 50 kg bags" --out spec.json
```

Invalid JSON or a schema miss exits with `RequirementsChecklist invalid` — Discovery should stop, not guess.

## Eval

```bash
python eval/run_eval.py
```
