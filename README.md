# claim2real

**Verified robotics sourcing: from a problem statement to a checked shortlist, a Build vs Buy call, and a list of people to contact.**

---

## 1. Executive summary

Teams building robots lose weeks sourcing parts. Specs are spread across vendor pages, resellers copy each other's claims, and a datasheet number is rarely checked against an independent source before a purchase order goes out.

claim2real turns a plain-English problem statement into a sourcing decision through a chain of focused agents:

| Stage | Output for the buyer |
|---|---|
| **Requirements** | A hardware and software bill of requirements, which the buyer can edit |
| **Discovery** | Candidate products and libraries for each requirement |
| **Catalog** | Each candidate's claimed specs, price and stock, taken from its own pages |
| **Verification** | Each claim checked against independent sources, plus a vendor-risk rating and a score |
| **Elimination** | A final list for each requirement. Every rejected option is listed with the reason |
| **Build vs Buy** | A buy, build or hybrid recommendation for each requirement, with reasons, risks and a next step |
| **Report & outreach** | A buyer briefing, the people to contact at each vendor, and email drafts ready to send |

Search runs on **Telem** (multi-provider web search and fetch). **Tavily** provides a second, independent opinion. Reasoning uses **Claude Haiku** (`claude-haiku-5-5`), the lowest-cost Claude model, at low effort with thinking off. A full run costs a few cents in LLM tokens.

---

## 2. The problem we address

| Pain point | What claim2real does about it |
|---|---|
| Vendor specs are self-reported | Each must-have claim is checked against sources *other than* the seller's and maker's own domains |
| Resellers and new storefronts look the same | The vendor-risk check looks at domain age, business type, independent footprint and contact details |
| Long candidate lists hide weak options | Options are eliminated by explicit rules, and the reason is shown for each one |
| Build vs Buy is decided by gut feel | Each requirement gets a recommendation backed by the verified evidence |
| Finding the right person to email takes time | The people at each manufacturer and seller are found, and a personalised draft is written for each |

---

## 3. How it works

```
 Problem statement
        │
        ▼
 ┌──────────────────┐   editable in the UI, saved back to the spec
 │ Requirements     │──────────────────────────────────────────┐
 └──────────────────┘                                          │
        │  hardware checklists            software needs        │
        ▼                                     ▼                 │
 ┌──────────────────┐                 ┌──────────────────┐      │
 │ Discovery        │ Telem search    │ Software         │      │
 │ (per component)  │                 │ discovery        │      │
 └──────────────────┘                 └──────────────────┘      │
        ▼                                     │                 │
 ┌──────────────────┐ Telem fetch            │                 │
 │ Catalog reader   │ + Tavily extract       │                 │
 └──────────────────┘                        ▼                 │
        ▼                             ┌──────────────────┐      │
 ┌──────────────────┐ Telem multi-    │ Software         │      │
 │ Claim verifier   │ provider search │ verification     │      │
 │ + scoring        │ + Tavily        │ (licence, upkeep)│      │
 └──────────────────┘                 └──────────────────┘      │
        └───────────────┬─────────────────────┘                 │
                        ▼                                       │
               Elimination → final list per requirement ◄───────┘
                        ▼
               Build vs Buy per requirement
                        ▼
               Final agent: briefing, key people, email drafts
```

Everything in a run shares **one Telem session**, so the trace of provider calls can be audited end to end.

---

## 4. The user journey (web UI)

1. **Problem statement.** The buyer describes the robot, the task and the constraints.
2. **Requirements.** Hardware is shown on the left and software on the right. Quantity, budget, lead time and each spec value can be edited, and components can be added or removed. **Save** writes the edits to the backend spec.
3. **Start search.** Discovery runs for each hardware and software requirement, using the saved spec.
4. **Start verification.** The catalog reader, claim verifier and software validator run. Rejected options are listed with reasons, the final list is shown for each requirement, and a Build vs Buy card sits at the top of each.
5. **Report & outreach** starts automatically. It has three tabs:
   - **Briefing:** the buyer report.
   - **People:** contacts with LinkedIn, email and source links.
   - **Email drafts:** editable, with *Copy* and *Open in mail* buttons.

   The report, the outreach file and the raw JSON can be downloaded from the UI.

Progress shows in a step tracker at the top. Each section can be expanded to show the evidence behind any verdict, along with the Telem provider trace.

---

## 5. Agent reference

Each agent is a self-contained folder with its own CLI, tests and `requirements.txt`. The UI runs the agents as subprocesses, so any agent can also be run on its own.

| Folder | Role | Main inputs → outputs | Key services |
|---|---|---|---|
| [`requirements_agent/`](requirements_agent/) | Problem → hardware checklists and software needs | text → `spec.json` | Claude |
| [`discovery_agent/`](discovery_agent/) | Batched multi-provider search, cleaning and ranking of product pages, top 10 shortlist | checklist → `discovery.json` | Telem search, Claude |
| [`catalog_agent/`](catalog_agent/) | Reads each candidate's pages and extracts one claim per spec field, with unit-aware matching | discovery → `catalog.json` | Telem fetch, Tavily extract, Claude |
| [`verifier_agent/`](verifier_agent/) | Checks claims independently, profiles vendor risk, scores candidates | catalog → `verified.json` and report | Telem multi-provider, Tavily, RDAP, Claude |
| [`software_agent/`](software_agent/) | Finds and validates libraries and SDKs: licence, cost model, maintenance, maturity, integration | spec → discovery → verified list | Telem, Tavily, Claude |
| [`decision_agent/`](decision_agent/) | Build vs Buy for each requirement, with a rule-based fallback | shortlist → `buildbuy.json` | Claude |
| [`final_agent/`](final_agent/) | Buyer briefing, key people, outreach drafts | verification report → `report.md`, `outreach.md/json` | Claude, Tavily |
| [`ui/`](ui/) | FastAPI server and the five-step web app. `workflow.py` orchestrates a run | browser ↔ `/api/*` | n/a |

---

## 6. Decision rules

### 6.1 Claim verification (hardware)
- Results from the seller's and maker's own domains are **excluded** as evidence.
- **Verified** needs at least 2 independent domains, or 1 authoritative source (distributor or datasheet) plus another item.
- **Contradicted** needs an independent source that is cited and valid.
- Anything else is **unverified**. The LLM can only cite numbered evidence, and code enforces these thresholds.

### 6.2 Score
```
score = 0.5 × requirement fit + 0.3 × verification ratio + 0.2 × vendor trust
```
Vendor trust is 1.0 for low risk, 0.5 for medium and 0.0 for high. A candidate that fails a must-have or is over budget is ranked last.

### 6.3 Elimination (applied in code, with the reason shown)

| Rule | Example reason shown |
|---|---|
| Fails a must-have | *Fails reach: 618 mm (needs ≥ 900 mm)* |
| Over budget | *Over budget: $1240 vs $500/unit* |
| Must-have contradicted by independent evidence | *Continuous torque contradicted by independent sources* |
| High vendor risk | *High vendor risk: domain registered 4 months ago* |
| No must-have confirmed | *No must-have spec confirmed on the vendor page* |
| Software: no valid supporting evidence, or judged unfit | The validator's stated reason |

Survivors make up the **final list**, up to 3 for each requirement. Software counts as *validated* when at least 2 distinct domains back it.

### 6.4 Build vs Buy
For each requirement the decision agent returns **buy**, **build** or **hybrid**, with a confidence level, reasons, risks and a concrete next step. If the LLM is unavailable, a rule-based fallback makes the call.

---

## 7. Reference run

Problem: *6-DOF arm, joint actuator ≥ 10 N·m continuous, ≤ 1.2 kg, CAN bus, under $500, ships to the US in ≤ 3 weeks.* The spec has one hardware requirement and two software requirements.

| Phase | Time | Outcome |
|---|---|---|
| Search | 18 s | 3 actuator candidates, 4 + 4 software candidates |
| Verification | 26 s | Actuator: 1 kept, 2 eliminated (one for vendor risk, one for 4 N·m continuous torque). Motion planning: MoveIt 2, OMPL and cuMotion kept, 1 eliminated |
| Build vs Buy | n/a | Actuator: **hybrid** · servo control: **buy** · motion planning: **buy** (MoveIt 2, high confidence) |
| Report & outreach | 137 s | Briefing, 20 contacts at 6 companies, 20 email drafts |
| Telem usage | n/a | 440 provider runs across 10 providers, 13 Tavily calls |

---

## 8. Getting started

**Prerequisites:** Python 3.12, plus API keys for Telem, Tavily and Anthropic.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r ui/requirements.txt -r requirements_agent/requirements.txt \
            -r software_agent/requirements.txt -r decision_agent/requirements.txt \
            -r final_agent/requirements.txt
```

Create `.env` in the repository root. **Never commit this file.** It is listed in `.gitignore`.

```ini
TELEM_API_KEY=...
TELEM_BASE_URL=https://hack.telem.ai/api
TAVILY_API_KEY=...
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-haiku-5-5
ANTHROPIC_EFFORT=low
ANTHROPIC_THINKING=off
```

Run the app:

```bash
python -m uvicorn app:app --app-dir ui --port 8000
# open http://127.0.0.1:8000
```

Run the offline tests. They are mocked, so they make no network calls and cost nothing:

```bash
for d in discovery_agent catalog_agent verifier_agent software_agent decision_agent; do
  (cd $d && ../.venv/bin/python -m pytest -q); done
```

Run data is written to `ui/data/runs/<run-id>/`, which is git-ignored. The file names are in the table below.

| File | Contents |
|---|---|
| `shortlist.json` | Final and eliminated lists for each requirement |
| `buildbuy.json` | Build vs Buy decisions |
| `hw*_report.md` | Vendor and claim verification report for each component |
| `report.md`, `outreach.md`, `outreach.json` | Buyer briefing, contacts, drafts |

---

## 9. Cost and performance

- **Model:** Claude Haiku (`claude-haiku-5-5`) at $0.10 in and $0.50 out per million tokens, with low effort and no extended thinking. A single-component pipeline measured about **1.6 cents** in LLM cost.
- **Parallelism:** up to 3 hardware components are processed at once, and software runs alongside them. Inside each agent, Telem queries are sent in batches.
- **Typical time:** about 4 minutes for a small spec. A six-component robot takes longer: about 2 minutes for search and 3–5 for verification.

---

## 10. Known limitations

- **Price and stock.** These vary across sellers, so a valid price at one store can show as *contradicted* by another.
- **Thin public data.** Niche parts may have little public data. Their must-haves stay *unverified* rather than being guessed.
- **Briefing accuracy.** The final agent's briefing is written by an LLM and can occasionally misstate a verified fact. The verification cards in the UI are the source of truth.
- **Contacts.** People are found through public web search. Check them before sending any email.

---

## 11. Repository map

```
claim2real/
├── requirements_agent/   problem → spec
├── discovery_agent/      Telem search → shortlist
├── catalog_agent/        Telem fetch + Tavily → claims
├── verifier_agent/       independent verification, vendor risk, scoring
├── software_agent/       software discovery + validation
├── decision_agent/       Build vs Buy
├── final_agent/          briefing, people, outreach drafts
└── ui/                   FastAPI app + orchestrator (workflow.py) + static front end
```
