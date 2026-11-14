# Catalog reader

Reads each shortlisted product page and returns a `CandidateProfile`: claims with quotes, converted to standard units, and a meets/fails/unknown result per requirement. It uses **Telem fetch**, with **Tavily Extract** as the fallback.

1. **Fetch:** Telem `fetch` in batches of 5, markdown, up to 15k characters, in the same session as Discovery.
2. **Fallback:** a page that failed, is under 500 characters, or is a bot wall goes to Tavily Extract, and `extraction_engine` becomes `"tavily"`.
3. **Extraction:** the LLM extracts claims only for the checklist's fields, plus related fields such as peak torque. Values and units are taken as written, each with a quote.
4. **Checks in code:**
   - the quote must be on the page and the number must be in the quote; otherwise the claim is dropped;
   - units are converted (`units.py`);
   - each requirement and the budget is marked meets, fails or unknown.

A failed page or LLM call is recorded in `page_status`, and the run continues.

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env    # or use the repo-root .env
```

## Run
```bash
python catalog.py ../discovery_agent/cache/discovery.json      # -> cache/catalog.json
python catalog.py ../discovery_agent/cache/discovery.json --limit 3
python -m pytest -q tests                                      # offline, mocked
```
