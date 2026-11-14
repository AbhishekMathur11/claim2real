# Discovery agent

Turns the Requirements agent's output (`{"checklists": [...]}` or a single checklist) into a shortlist of 6–8 candidate products per component, using **Telem search**. Every component is searched in one Telem session.

1. **Query plan:** the LLM writes 5–8 queries across five angles (spec, budget, alternative, recency, distributor). Code fills in any missing angle, so this step still works when the LLM is down.
2. **Three Telem calls in one session:**
   - open-web queries, with `goal` and `auto_routing="accuracy"`;
   - recency queries, with `published_after` (about 18 months back);
   - distributor queries, with `include_domains`.
3. **Merge:** "found by" labels come from Telem's per-provider results. Duplicates are removed by URL, then by vendor domain plus title.
4. **Shortlist:** the LLM picks by index, so it can't invent URLs. Without the LLM, a ranking that favours product pages takes over.

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env    # or use the repo-root .env (this folder's .env is read first)
```
For the hackathon key, `TELEM_BASE_URL` must be `https://hack.telem.ai/api`.

## Run
```bash
python discovery.py fixtures/actuator_checklist.json          # -> cache/discovery.json
python discovery.py ../requirements_agent/spec.json --component 0
python -m pytest -q tests                                      # offline, mocked
```
`cache/discovery.json` is the input to `catalog_agent`.
