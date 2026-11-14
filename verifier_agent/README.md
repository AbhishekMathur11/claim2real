# Claim verifier + scoring

Checks each candidate's claims against independent sources, gives a vendor-risk signal, and ranks the candidates. It uses **Telem multi-provider search** with **Tavily** as a second opinion, all in the run's existing Telem session.

1. **Pick claims:** up to 4 per candidate. Must-have claims come first, then price, then availability.
2. **Telem:** one batched `AsyncTelem` search per candidate, with candidates running in parallel. Settings are `auto_routing="accuracy"`, `max_routing_providers=3` and `context="verify vendor claims for <model>"`. Each batch has:
   - one datasheet query per claim;
   - a review query;
   - a price and stock query;
   - a `<vendor> reviews complaints` query.
3. **Tavily:** one advanced search per must-have claim.
4. **Independence:** results from the seller's domain and the vendor's own domain are removed. Distributors and datasheets/PDFs count as authoritative.
5. **Judge:** the LLM uses only the numbered evidence. Code then enforces the rules:
   - `verified` needs at least 2 independent domains, or 1 authoritative source plus another item;
   - `contradicted` needs a valid cited independent item;
   - anything else is downgraded to `unverified`.

   **Without the LLM**, a rule-based matcher is used instead: the model name and the value must both appear in independent evidence.
6. **Vendor risk:** the LLM's assessment, plus code checks for a free-mail or mismatched contact domain and for little independent footprint. The higher of the two wins.
7. **Vendor and product report.** A second batched Telem search per candidate looks at the seller's history (founded, about) and at real-world use of the product (builds, GitHub, forums). The seller domain's registration date comes from public RDAP (`domain_age.py`). The judge also returns:
   - ratings for 7 vendor criteria: time in market, footprint, business type, reviews, spec accuracy, price consistency, contact;
   - the independent value next to each claimed spec;
   - the manufacturer's background;
   - the release year and deployment examples;
   - technical and commercial summaries, and a recommendation.

   Code overrides the LLM where it has hard data. A seller domain younger than 1 year is a concern. *Spec accuracy* comes from the claim verdicts. A "contradicted" verdict whose independent value repeats the claimed number is re-checked. Up to 2 of the seller's own About/Contact pages are shown labelled self-reported, for vendor facts only.
8. **Score** (`scoring.py`): `0.5*fit + 0.3*verification + 0.2*trust`. Fit is the share of must-haves plus budget that are met. A must-have that fails, or a price over budget, ranks the candidate last.

## Run
```bash
python verifier.py ../catalog_agent/cache/catalog.json            # -> cache/verified.json + cache/verified_report.md
python verifier.py ../catalog_agent/cache/catalog.json --limit 3
python -m pytest -q tests                                         # offline, mocked
```
