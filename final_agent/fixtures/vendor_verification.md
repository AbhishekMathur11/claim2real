# Vendor and claim verification report

Generated 2026-11-14  ·  Telem session `fcd49ebe-783c-4926-9e36-985b279df678`  ·  180 Telem provider runs across 9 providers, 5 Tavily searches

## How candidates were judged

**Evidence.** Each candidate gets two batched Telem searches in the run's session (`auto_routing=accuracy`, up to 3 providers per query): one about its claims (datasheet, price, stock, reviews, complaints) and one about the seller's history and real-world use of the product (builds, GitHub, forums). Tavily runs a second search for each must-have claim. Results from the seller's own domain and the vendor's own domain are discarded, so only independent sources count. The seller domain's registration date comes from the public RDAP registry.

**Claim verdicts.** Claude compares each claim on the seller's page with the numbered independent evidence and may not use outside knowledge. Code then enforces these rules:
- ✅ **verified** needs 2 or more independent domains stating the same value, or one authoritative source (a datasheet, manual or major distributor) plus one other item.
- ❌ **contradicted** needs an independent item about this model giving a materially different value (>10% for numbers), or showing that the figure is peak rather than continuous, or that the interface is different.
- ❔ **unverified** means neither rule was met; it is not a negative finding.

**Vendor criteria.** Each one is rated positive / neutral / concern / unknown, with the finding and its sources:
- **Time in market**: how long the seller has operated: founding year in evidence, the registry facts, earliest mentions.
- **Company footprint**: independent presence: distributors, press, wikis, marketplaces, social profiles.
- **Business type & sales channel**: manufacturer, authorized distributor, reseller or marketplace seller; is the channel known.
- **Customer reviews & complaints**: reviews, ratings, complaint or fraud reports about the seller.
- **Spec accuracy**: do the seller's stated specs match independent sources (use the claim verdicts).
- **Price consistency**: is the seller's price in line with other sellers of the same model.
- **Contact & transparency**: company name, address and contact details stated and consistent.

The seller's own About/Contact pages (at most 2) are shown to Claude labelled *self-reported*. They can inform business type and contact details only; code stops them from supporting or contradicting any claim and from counting as independent footprint. *Spec accuracy* is set by code from the claim verdicts.

Code checks can only make a rating worse: a seller domain younger than 1 year is a *Time in market* concern, and a free-mail or mismatched contact domain is a *Contact* concern. The overall vendor risk is whichever is higher, Claude's rating or the code checks.

**Time in market and real-world use.** The product's release year is taken from the evidence. The earliest independent mention is the oldest `publish_date` that Telem or Tavily returned for a page naming the model. Deployment examples are concrete builds, papers, integrations, reviews, forum threads or repos, each linked.

**Score** = 0.5 × fit + 0.3 × verification + 0.2 × trust.
- *fit*: the share of must-haves plus budget that the seller page meets (unknown counts as not met).
- *verification*: (verified − contradicted) ÷ claims checked, never below 0.
- *trust*: 1.0 for low vendor risk, 0.5 for medium, 0 for high.
- A candidate that fails a must-have or is over budget is ranked below all the others.

## robot joint actuator

*6-DOF arm for pick-and-place. Need a joint actuator: >=10 Nm continuous torque, <=1.2 kg, CAN bus, under $500, ships to the US in <=3 weeks.*

**Must-haves:** continuous_torque_nm >= 10 N·m; mass_kg <= 1.2 kg; comm_interface has CAN  ·  **Budget:** $500/unit  ·  **Lead time:** ≤ 21 days to US

| # | Product | Seller | Score | Risk | Verified / contradicted | Meets reqs |
|---|---|---|---|---|---|---|
| 1 | DAMIAO DM-J10010-2EC Integrated Brushless Motor | ZennixTek | 0.65 | medium | 2 / 0 of 2 | yes |
| 2 | DAMIAO DM-J4340-2EC Integrated Robotic Joint Actuator | RobX / RobotShop | 0.47 | medium | 1 / 2 of 4 | yes |
| 3 | MyActuator RMD-X4-10 Planetary Actuator 10Nm Dual Encoder EtherCAT+CAN Robot Joint Drive | NanoVolt Technology | 0.30 | high | 1 / 0 of 1 | no |

### 1. DAMIAO DM-J10010-2EC Integrated Brushless Motor
Seller **ZennixTek** ([zennixtek.com](https://www.zennixtek.com/products/damiao-dm-j10010-2ec-integrated-brushless-motor))  ·  score **0.65**  ·  vendor risk **medium**

> **Recommendation:** Ask ZennixTek for the official datasheet, a verifiable business registration and contact address, and proof of authorization from DAMIAO before purchase, or buy from an established reseller or the manufacturer's own channel with a documented return policy.

**Score breakdown**

| Component | Value | Weight | Contribution |
|---|---|---|---|
| Requirement fit | 0.50 | 0.5 | 0.250 |
| Claim verification | 1.00 | 0.3 | 0.300 |
| Vendor trust (medium risk) | 0.50 | 0.2 | 0.100 |
| **Total** | | | **0.650** |

#### Technical: stated vs independent specs

| Spec | Seller states | Independent sources say | Verdict | Sources |
|---|---|---|---|---|
| continuous_torque_nm | 40.0 N·m — “Rated Torque \| 40 Nm” | Rated/nominal torque 40 N·m (peak 150 N·m) | ✅ verified | [actuatorlist.com](https://actuatorlist.com/actuators/damiao-dm-j10010-2ec), [alibaba.com](https://www.alibaba.com/product-detail/Dual-Encoder-Integrated-Motor-and-Driver_1601831254804.html) |
| comm_interface | CAN @ 1 Mbps | CAN bus communication (MIT-mode CAN control) | ✅ verified | [roboticscenter.ai](https://www.roboticscenter.ai/store/product/damiao-dm-j10010-2ec-48v), [super.site](https://aifitlab-wiki.super.site/damiao-docs/dm-j10010-2ec-v10-motor-instruction-manual) |

| Requirement | Needed | Seller page |
|---|---|---|
| continuous_torque_nm | continuous_torque_nm >= 10 N·m | ✅ meets |
| mass_kg | mass_kg <= 1.2 kg | ❔ unknown |
| comm_interface | comm_interface has CAN | ✅ meets |
| budget | ≤ $500 | ❔ unknown (no price) |

#### Product maturity and real-world use

- **Released:** not stated in evidence
- **Manufacturer:** Shenzhen Damiao Technology Co., Ltd., founded 2019

| Criterion | Rating | Finding |
|---|---|---|
| Time in market | ⚠️ concern | Seller domain zennixtek.com registered 2025-10-17 (~1.1 years) |
| Spec accuracy | ✅ positive | 2 of 2 checked specs confirmed |
| Contact & transparency | ⚠️ concern | Contact details only self-reported |

**Vendor risk: medium**

### 2. DAMIAO DM-J4340-2EC Integrated Robotic Joint Actuator
Seller **RobX / RobotShop** ([robotshop.com](https://www.robotshop.com/products/robx-damiao-dm-j4340-2ec-integrated-robotic-joint-actuator-12-nm-rated-40-nm-peak-torque-absolute-encoders-can))  ·  score **0.47**  ·  vendor risk **medium**

> **Recommendation:** Ask the seller for a datasheet specifying the exact variant and rated torque, request a written contact and confirmed stock date, and compare against independent suppliers listing the model at about $155.

| Spec | Seller states | Independent sources say | Verdict |
|---|---|---|---|
| continuous_torque_nm | 12.0 N·m rated | 9 N·m rated (V3); 12 N·m (V4) | ❌ contradicted |
| comm_interface | CAN, UART | CAN 1 Mbps; no UART | ✅ verified |
| price_usd | 310 USD | ~$130–$215, commonly $155 | ❌ contradicted |

**Vendor risk: medium** — long-established RobotShop domain (2004) but 12 N·m claim does not match the standard 9 N·m rating and $310 is about double independent prices.

### 3. MyActuator RMD-X4-10 Planetary Actuator
Seller **NanoVolt Technology** ([nanovolttech.com](https://www.nanovolttech.com/product/myactuator-rmd-x4-10-planetary-actuator-10nm-dual-encoder-ethercat-can-robot-joint-drive/))  ·  score **0.30**  ·  vendor risk **high**  ·  ❌ does not meet requirements

> **Recommendation:** Ask the seller for a datasheet, company registration and contact details before buying, and confirm continuous versus peak torque. Consider an established distributor.

| Spec | Seller states | Independent sources say | Verdict |
|---|---|---|---|
| continuous_torque_nm | 4.0 N·m | Rated 4 N·m; peak 10 N·m | ✅ verified (fails >= 10 N·m must-have) |

**Vendor risk: high** — nanovolttech.com registered 2026-03-11 (~0.7 years), no independent footprint.
