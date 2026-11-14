# Final agent

Reads a **Vendor and claim verification report** (the Catalog output: ranked products, sellers, verified/contradicted claims, vendor risk). Claude writes a buyer briefing from that evidence, then Tavily finds people at the manufacturer and the seller and drafts emails.

No Google API. Drafts are files only.

## Input

The verification markdown, for example `fixtures/vendor_verification.md`. Identity is required:

```bash
python outreach.py --input fixtures/vendor_verification.md \
  --from-name "Jane Doe" --from-company "Northwind Automation"
```

Writes `output/report.md` (briefing), `output/outreach.md` (people + drafts), `output/outreach.json`.
