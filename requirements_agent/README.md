# Requirements agent

Turns a robotics / physical-AI problem into Catalog-valid `RequirementsChecklist` JSON. A narrow part request becomes one checklist. A system (3D bin picking, factory mapping AMR) becomes 2–5 checklists — camera, arm, gripper, mobile base, lidar, compute — each with its own `search_terms` and numeric `must_have`. Field names match Catalog scoring (`config.CANONICAL_FIELDS`). No vendor search.

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
