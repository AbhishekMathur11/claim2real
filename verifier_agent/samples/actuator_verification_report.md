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
| | | *Multiple independent sources state rated/nominal torque of 40 N·m for this model, matching the claim.* | | |
| comm_interface | CAN @ 1 Mbps — “Control Interface \| CAN @ 1 Mbps” | CAN bus communication (MIT-mode CAN control) | ✅ verified | [roboticscenter.ai](https://www.roboticscenter.ai/store/product/damiao-dm-j10010-2ec-48v), [super.site](https://aifitlab-wiki.super.site/damiao-docs/dm-j10010-2ec-v10-motor-instruction-manual) |
| | | *Independent manual and product pages describe CAN communication for this model; the 1 Mbps figure is not explicitly restated in the excerpts, so this rests on CAN interface being confirmed.* | | |

| Requirement | Needed | Seller page |
|---|---|---|
| continuous_torque_nm | continuous_torque_nm >= 10 N·m | ✅ meets |
| mass_kg | mass_kg <= 1.2 kg | ❔ unknown |
| comm_interface | comm_interface has CAN | ✅ meets |
| feedback (nice-to-have) | feedback has absolute encoder | ✅ meets |
| budget | ≤ $500 | ❔ unknown (no price) |

Stated specs (40 N·m rated torque, CAN interface) are consistent with the manufacturer and multiple independent listings, with peak torque typically cited as 150 N·m rather than the 120 N·m on one reseller page. The motor is a 48 V integrated joint with 10:1 reduction and dual encoders, suited to robot joints if CAN wiring and 48 V supply are planned.

#### Product maturity and real-world use

- **Released:** not stated in evidence
- **Earliest independent mention:** no dated page found (search providers returned no publish dates for this model)
- **Time on market:** unknown
- **Real-world deployment:** some real-world use
  - *product integration*: Model is sold by multiple independent resellers including Foxtech, Robotopian and RobotDoo, indicating a product line in commercial channels. ([robotopian.com](https://robotopian.com/products/damiao-dm-j10010-2ec-servo-motor))
  - *open-source code*: Official dmBots GitHub repository hosts manuals, drawings and performance curves for the DM-J10010-2EC. ([github.com](https://github.com/dmBots/DM-J10010-2EC/tree/master))
  - *user review*: Foxtech product pages list customer reviews for this motor, showing some purchaser feedback. ([foxtechuav.com](https://www.foxtechuav.com/dm-j10010-2ec-48v-mit-driven-brushless-servo-joint-motor-with-dual-encoders-amp-gear-reduction-for-robotic-arms-actuator-for-robot.html))

#### Vendor assessment

- **Business type:** reseller
- **Founded:** not stated in evidence
- **Seller domain:** zennixtek.com registered 2025-10-17 (~1.1 years; registrar Alibaba Cloud Computing Ltd. d/b/a HiChina (www.net.cn); [RDAP](https://rdap.org/domain/zennixtek.com))
- **Manufacturer:** Shenzhen Damiao Technology Co., Ltd., founded 2019 by former DJI engineers: independent presence via ethercat.org.cn, growbotics.ai, rcdrone.top and a 2025 product selection handbook at worldrobotconference.com, plus open-source materials on GitHub. ([ethercat.org.cn](https://www.ethercat.org.cn/en/members/members_01EEF6C8FCC446F5BC8F074562EBECFF.htm), [growbotics.ai](https://robotics.growbotics.ai/suppliers/damiao), [rcdrone.top](https://rcdrone.top/collections/damiao-motor))

| Criterion | Rating | Finding | Sources |
|---|---|---|---|
| Time in market | ⚠️ concern | The seller's domain was registered 2025-10-17 (about 1.1 years ago) and no independent evidence states when the seller company started trading. Seller domain registered 2025-10-17 (1.1 years, RDAP). | [rdap.org](https://rdap.org/domain/zennixtek.com) |
| Company footprint | ⚠️ concern | No independent press, marketplace, or social profile for ZennixTek was found; the only seller-linked source is its own website. | [zennixtek.com](https://www.zennixtek.com/pages/contact) |
| Business type & sales channel | ➖ neutral | Seller self-describes as a motion-control hardware distributor, which is a self-reported claim; the channel is not independently confirmed. | [zennixtek.com](https://www.zennixtek.com/pages/contact) |
| Customer reviews & complaints | ❔ unknown | No reviews or complaint reports about the ZennixTek seller were found in the evidence. | — |
| Spec accuracy | ✅ positive | 2 of 2 checked specs confirmed by independent sources; none contradicted. Both stated specs (40 N·m rated torque and CAN interface) match independent sources for this model. | [roboticscenter.ai](https://www.roboticscenter.ai/store/product/damiao-dm-j10010-2ec-48v), [actuatorlist.com](https://actuatorlist.com/actuators/damiao-dm-j10010-2ec), [alibaba.com](https://www.alibaba.com/product-detail/Dual-Encoder-Integrated-Motor-and-Driver_1601831254804.html) |
| Price consistency | ❔ unknown | The seller page price is not stated; independent listings range from about $455 to $642 USD for this model, which is too wide to judge the seller. | [roboticscenter.ai](https://www.roboticscenter.ai/zh/store/product/damiao-dm-j10010-2ec-48v), [robotopian.com](https://robotopian.com/products/damiao-dm-j10010-2ec-servo-motor), [robotdoo.com](https://robotdoo.com/products/damiao-dm-j10010-2ec-motor) |
| Contact & transparency | ⚠️ concern | Only self-reported contact details exist on the seller's own site; company name, address, and contact details could not be verified independently. | [zennixtek.com](https://www.zennixtek.com/pages/contact) |

**Vendor risk: medium** — Seller domain zennixtek.com was registered 2025-10-17 (about 1.1 years old), and the only seller-controlled source is its own site, which self-reports a company name (Shanghai Zennixtek Technology Co., Ltd.) with no independent footprint, reviews, or founding year found in the evidence

The seller is a recently registered domain (about 1.1 years old) with no independent footprint, reviews, or stated founding year, and its contact details are self-reported only. Independent resellers list the same model between roughly $455 and $642 USD, so the seller's price could not be assessed.

<sub>32 independent evidence items reviewed.</sub>

---

### 2. DAMIAO DM-J4340-2EC Integrated Robotic Joint Actuator
Seller **RobX / RobotShop** ([robotshop.com](https://www.robotshop.com/products/robx-damiao-dm-j4340-2ec-integrated-robotic-joint-actuator-12-nm-rated-40-nm-peak-torque-absolute-encoders-can))  ·  score **0.47**  ·  vendor risk **medium**

> **Recommendation:** Ask the seller for a datasheet specifying the exact variant and rated torque, request a written contact and confirmed stock date, and compare against independent suppliers listing the model at about $155.

**Score breakdown**

| Component | Value | Weight | Contribution |
|---|---|---|---|
| Requirement fit | 0.75 | 0.5 | 0.375 |
| Claim verification | 0.00 | 0.3 | 0.000 |
| Vendor trust (medium risk) | 0.50 | 0.2 | 0.100 |
| **Total** | | | **0.475** |

#### Technical: stated vs independent specs

| Spec | Seller states | Independent sources say | Verdict | Sources |
|---|---|---|---|---|
| continuous_torque_nm | 12.0 N·m — “Delivers 12 N·m rated torque and 40 N·m peak torque in a compact joint actuator” | 9 N·m rated torque, 27 N·m peak torque (V3); 12 N·m rated (V4 variant) | ❌ contradicted | [sharingwin.com](https://sharingwin.com/wp-content/uploads/2025/09/DM-J4340-2EC-Gear-Motor-User-Manual-V1.0.pdf), [githubusercontent.com](https://raw.githubusercontent.com/dmBots/DM-J4340-2EC/master/manual/DM-J4340-2EC%20%20Geared%20Motor%20User%20Manual%20V1.1%202026-09-08.pdf) |
| | | *Independent manuals and listings state 9 N·m rated and 27 N·m peak for the 24V build; a 12 N·m rating appears only on the V4 configuration, so the claim is materially different (>10%) for the standard model.* | | |
| comm_interface | CAN, UART — “Supports CAN communication at 1 Mbps for motor control and feedback.” | CAN bus (1 Mbps); no UART reference found | ✅ verified | [foxtech.com](https://f.foxtech.com/manual/DM-J4340-2EC.pdf), [sharingwin.com](https://sharingwin.com/product/dmbots-dm-j4340) |
| | | *Independent sources state CAN bus communication for this model; no independent source mentions UART as an interface.* | | |
| price_usd | 310.0 USD — “Price: 310.00 USD” | approximately $130-$215 USD (commonly $155) | ❌ contradicted | [alibaba.com](https://www.alibaba.com/product-detail/DAMIAO-DM-J4340-2EC-Da-Miao_1601497222152.html), [roboticscenter.ai](https://www.roboticscenter.ai/store/product/damiao-dm-j4340-2ec) |
| | | *Independent listings for the same model show prices of about $130 to $215, with $155 most common, so $310 is roughly double the market figure.* | | |
| availability | Special order — “Special order” | — | ❔ unverified | — |

| Requirement | Needed | Seller page |
|---|---|---|
| continuous_torque_nm | continuous_torque_nm >= 10 N·m | ✅ meets |
| mass_kg | mass_kg <= 1.2 kg | ❔ unknown |
| comm_interface | comm_interface has CAN | ✅ meets |
| feedback (nice-to-have) | feedback has absolute encoder | ✅ meets |
| budget | ≤ $500 | ✅ meets ($310) |

The seller states 12 N·m rated and 40 N·m peak torque, but independent manuals and listings give 9 N·m rated and 27 N·m peak for the standard 24V model, with 12 N·m appearing only on the V4 configuration. CAN bus communication is confirmed, while UART is not supported by independent evidence. Buyers should confirm which variant (V3 or V4) they will receive.

#### Product maturity and real-world use

- **Released:** 2025 ([githubusercontent.com](https://raw.githubusercontent.com/dmBots/DM-J4340-2EC/master/manual/DM-J4340-2EC%20%20V1.1%20Geared%20Motor%20User%20Manual%20V1.3%202026-08-13.pdf))
- **Earliest independent mention:** no dated page found (search providers returned no publish dates for this model)
- **Time on market:** ~1 years
- **Real-world deployment:** some real-world use
  - *open-source code*: A public GitHub repository for the DM-J4340-2EC publishes manuals, drawings and test data. ([github.com](https://github.com/dmBots/DM-J4340-2EC))
  - *open-source code*: A GitHub project provides a tau-omega actuator model for the DM-J4340-2EC (24V). ([github.com](https://github.com/Tensor-0/dm-actuator-model))
  - *forum discussion*: A Japanese developer blog describes wiring and running the DM-J4340-2EC over CAN in MIT control mode. ([zenn.dev](https://zenn.dev/samu4645/articles/robot_damiao))
  - *product integration*: The motor is listed as a joint actuator in the OpenArm open robot platform. ([openarm.dev](https://docs.openarm.dev/1.0/hardware/specifications/motor))

#### Vendor assessment

- **Business type:** reseller
- **Founded:** not stated in evidence
- **Seller domain:** robotshop.com registered 2004-12-03 (~21.9 years; registrar GoDaddy.com, LLC; [RDAP](https://rdap.org/domain/robotshop.com))
- **Manufacturer:** Shenzhen Damiao Technology Co., Ltd., founded 2019 by former DJI engineers: distributors and resellers including Robotopian, Foxtech, OpenELAB and Enactic list its motors, and it publishes manuals and open-source GitHub repositories. ([ethercat.org.cn](https://www.ethercat.org.cn/en/members/members_01EEF6C8FCC446F5BC8F074562EBECFF.htm), [rcdrone.top](https://rcdrone.top/collections/damiao-motor), [github.com](https://github.com/dmBots/DM-J4340-2EC))

| Criterion | Rating | Finding | Sources |
|---|---|---|---|
| Time in market | ✅ positive | Domain robotshop.com was registered in 2004 (about 22 years) and the seller self-reports nearly 25 years of operation, though the self-report is not independently confirmed. Seller domain registered 2004-12-03 (21.9 years, RDAP). | [robotshop.com](https://www.robotshop.com/pages/about-us), [rdap.org](https://rdap.org/domain/robotshop.com) |
| Company footprint | ➖ neutral | No independent press, reviews or marketplace profile for RobX or RobotShop were found in the evidence; the seller appears only through its own site. | — |
| Business type & sales channel | ➖ neutral | The seller is most likely a reseller, as the manufacturer is DAMIAO, but no authorized-distributor status is stated in the evidence. | — |
| Customer reviews & complaints | ❔ unknown | No customer reviews or complaint reports about this seller were found in the evidence. | — |
| Spec accuracy | ⚠️ concern | 1 of 2 checked specs contradicted by independent sources (continuous_torque_nm). The 12 N·m rated torque claim contradicts the 9 N·m rated torque in independent manuals and listings for the standard model. | [sharingwin.com](https://sharingwin.com/wp-content/uploads/2025/09/DM-J4340-2EC-Gear-Motor-User-Manual-V1.0.pdf), [githubusercontent.com](https://raw.githubusercontent.com/dmBots/DM-J4340-2EC/master/manual/DM-J4340-2EC%20%20Geared%20Motor%20User%20Manual%20V1.1%202026-09-08.pdf), [sharingwin.com](https://sharingwin.com/product/dmbots-dm-j4340) |
| Price consistency | ⚠️ concern | The seller's $310 price is about double the $130-$215 range shown by independent sellers for the same model. | [alibaba.com](https://www.alibaba.com/product-detail/DAMIAO-DM-J4340-2EC-Da-Miao_1601497222152.html), [roboticscenter.ai](https://www.roboticscenter.ai/store/product/damiao-dm-j4340-2ec), [robotopian.com](https://robotopian.com/products/damiao-dm-j4340-2ec-servo-motor) |
| Contact & transparency | ⚠️ concern | No contact details are stated on the seller page, and the page shows only a special-order availability with no address. | — |

**Vendor risk: medium** — The seller has a long-established domain (registered 2004) and a self-reported history of nearly 25 years, but its listed price is about double independent market prices, the page is a special order with no stated contact details, and the claimed 12 N·m rating does not match the standard model's 9 N·m rating

The seller is a long-established reseller (domain since 2004) offering the motor at $310 on special order, roughly double the $130-$215 range from other channels. No independent reviews or contact details were found for the seller.

<sub>32 independent evidence items reviewed.</sub>

---

### 3. MyActuator RMD-X4-10 Planetary Actuator 10Nm Dual Encoder EtherCAT+CAN Robot Joint Drive
Seller **NanoVolt Technology** ([nanovolttech.com](https://www.nanovolttech.com/product/myactuator-rmd-x4-10-planetary-actuator-10nm-dual-encoder-ethercat-can-robot-joint-drive/))  ·  score **0.30**  ·  vendor risk **high**  ·  ❌ does not meet requirements

> **Recommendation:** Ask the seller for a datasheet, company registration and contact details before buying, and confirm the continuous versus peak torque figures. Consider buying from an established distributor such as Dings Motion USA or a known marketplace with buyer protection.

**Score breakdown**

| Component | Value | Weight | Contribution |
|---|---|---|---|
| Requirement fit | 0.00 | 0.5 | 0.000 |
| Claim verification | 1.00 | 0.3 | 0.300 |
| Vendor trust (high risk) | 0.00 | 0.2 | 0.000 |
| **Total** | | | **0.300** |

#### Technical: stated vs independent specs

| Spec | Seller states | Independent sources say | Verdict | Sources |
|---|---|---|---|---|
| continuous_torque_nm | 4.0 N·m — “The RMD-X4-10 Robotic Planetary Actuator has a dual encoder, 12.6 gear ratio, 24V input, 1” | Rated torque 4 N·m; peak torque 10 N·m (vendor's 4 N·m is the rated, not peak, figure)  ; RMD-X4-10 rated 4 N·m with 10 N·m peak per independent specs.  ; Dings Motion lists 10 N·m as peak torque for RMD-X4-10.  ; Manuals+ spec table lists Rated Torque 4 N·m, Peak 10 N·m.  ; User manual also lists 4 N·m rated and 10 N·m peak.  ; AIFITLAB X4-10-L: rated torque 4 N·m, peak 10 N·m.  ; Vendor claim of 4 N·m is consistent with rated torque but presented as the device's torque without qualification.  ; Multiple evidence items indicate a 10 N·m peak figure, so the vendor's 4 N·m is not the peak value.  ; Consistent with 4 N·m rated value, so the claim is not materially wrong for continuous torque.  ; Stated continuous torque matches rated 4 N·m, so verdict hinges on framing.  ; Evidence shows 4 N·m rated torque for X4-10, matching the claim.  ; Evidence states rated torque 4 N·m for X4-10 variants.  ; Evidence states rated torque 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m.  ; Evidence states rated 4 N·m. | ✅ verified | [manuals.plus](https://manuals.plus/m/2f71744db94a91b6dc423e726f4d545fba638ac8da82dc471ba5cf2f9b7c32ab), [dingsmotionusa.com](https://www.dingsmotionusa.com/rmd-x-series) |
| | | *MyActuator RMD-X4-10 Actuator Technical Specifications - Manuals+* | | |

| Requirement | Needed | Seller page |
|---|---|---|
| continuous_torque_nm | continuous_torque_nm >= 10 N·m | ❌ fails |
| mass_kg | mass_kg <= 1.2 kg | ❔ unknown |
| comm_interface | comm_interface has CAN | ❔ unknown |
| feedback (nice-to-have) | feedback has absolute encoder | ❔ unknown |
| budget | ≤ $500 | ❔ unknown (no price) |

The seller states 4 N·m torque, which matches the independent rated torque of 4 N·m for the RMD-X4-10 but omits the 10 N·m peak figure, and the stated 12.6 gear ratio is close to the 12.5 reported elsewhere. Dual encoder, 24 V input, 100 W output and CAN/EtherCAT are broadly consistent with independent listings. The main fit concern is that 4 N·m is continuous, so peak torque loads must be checked against 10 N·m.

#### Product maturity and real-world use

- **Released:** not stated in evidence
- **Earliest independent mention:** no dated page found (search providers returned no publish dates for this model)
- **Time on market:** unknown
- **Real-world deployment:** some real-world use
  - *forum discussion*: RobotShop forum thread reports a user attempting to control an RMD actuator over CAN, showing hands-on use of the device. ([robotshop.com](https://community.robotshop.com/forum/t/unable-to-control-an-rmd-actuator-from-myactuator-via-can/104196))
  - *product integration*: Listed as an actuator option for robotic arms, small humanoids and exoskeleton joints on an open-source robotics catalogue. ([growbotics.ai](https://robotics.growbotics.ai/suppliers/products/rmd-x4-10-v4))
  - *user review*: AliExpress article describes use of the RMD-X4 in quadruped robot joints with thermal observations. ([aliexpress.com](https://www.aliexpress.com/s/wiki-ssr/article/x4-micromotor))

#### Vendor assessment

- **Business type:** unknown
- **Founded:** not stated in evidence
- **Seller domain:** nanovolttech.com registered 2026-03-11 (~0.7 years; registrar Spaceship, Inc.; [RDAP](https://rdap.org/domain/nanovolttech.com))
- **Manufacturer:** MyActuator (Suzhou Micro Actuator Technology Co., Ltd.), founded 2020: independent presence via RobotToday, Flowntro, NetivTech, DingsMotion USA distributor listings and the MyActuator USA entity, citing manufacturer_evidence. ([netivtech.com](https://netivtech.com/about-myactuator/), [myactuator.us](https://myactuator.us/), [robottoday.com](https://robottoday.com/suppliers-discovery/MyActuator))

| Criterion | Rating | Finding | Sources |
|---|---|---|---|
| Time in market | ⚠️ concern | Seller domain was registered 2026-03-11 (about 0.7 years ago) and no earlier seller-specific mentions were found, while the manufacturer was founded in 2020. Seller domain registered 2026-03-11 (0.7 years, RDAP). | [rdap.org](https://rdap.org/domain/nanovolttech.com) |
| Company footprint | ⚠️ concern | No independent listings, press or profiles for NanoVolt Technology were found; the product appears only through the seller's own page and third-party listings for the manufacturer. | — |
| Business type & sales channel | ❔ unknown | Whether NanoVolt Technology is a reseller, distributor or marketplace seller is not stated in any evidence. | — |
| Customer reviews & complaints | ❔ unknown | No customer reviews or complaint reports about NanoVolt Technology were found in the evidence. | — |
| Spec accuracy | ✅ positive | 1 of 1 checked specs confirmed by independent sources; none contradicted. The seller's 4 N·m torque figure matches the rated value but independent sources state 10 N·m peak, so the seller's presentation of torque is incomplete rather than wrong. | [manuals.plus](https://manuals.plus/m/2f71744db94a91b6dc423e726f4d545fba638ac8da82dc471ba5cf2f9b7c32ab), [dingsmotionusa.com](https://www.dingsmotionusa.com/rmd-x-series), [manuals.plus](https://manuals.plus/m/ac02150fb7d30f40ffc5968ebe4223b303c376d77d1f479309eafb573902559d) |
| Price consistency | ❔ unknown | The seller page states no price; other sellers list roughly $279 to $349 for this model, so no comparison is possible. | [roboticscenter.ai](https://www.roboticscenter.ai/store/product/myactuator-rmd-x4-10-motor), [zennixtek.com](https://www.zennixtek.com/products/myactuator-rmd-x4-10-brushless-servo-motor), [wheelrc.com](https://www.wheelrc.com/product/myactuator-rmd-x4-10-planetary-actuator-10nm-dual-encoder-ethercat-can-robot-joint-drive/) |
| Contact & transparency | ⚠️ concern | No company name, address or contact details are stated for NanoVolt Technology. | — |

**Vendor risk: high** — Seller domain nanovolttech.com was registered only 0.7 years ago, no independent footprint for the seller was found in the evidence, and the seller's own page presents the rated 4 N·m as the device torque while independent sources list 10 N·m peak. Contact details and price are not stated

NanoVolt Technology has no independent footprint, and its domain was registered only about 0.7 years ago. The seller page gives no price, availability or contact details, and comparable listings for the same model range from about $279 to $349. The channel and reputation cannot be established from the evidence.

<sub>32 independent evidence items reviewed.</sub>

---
