# Domain Term Definitions

Terms that appear in DAB queries but are NOT defined in any schema.
The agent must know these definitions before answering — they cannot be inferred from column names alone.

---

## Cross-domain terms

| Term | Correct definition | Common wrong interpretation |
|---|---|---|
| "average rating" | Mean of `rating` column across selected rows | Do not use `rating_number` (which is count of ratings, not the rating score) |
| "number of reviews" | COUNT of review rows | Do not use `review_count` from a metadata table unless the query explicitly asks for it |
| "active" business/account | Defined per dataset — see below | Do NOT use row existence as a proxy |
| "pass@1" (evaluation) | Fraction of queries answered correctly on the first attempt | Not pass@k with sampling |

---

## yelp

| Term | Definition |
|---|---|
| "open business" | `is_open = 1` in the `business` collection |
| "closed business" | `is_open = 0` |
| "elite user" | User whose `elite` field contains at least one year string |
| "check-in" | One entry in the `date` list array in the `checkin` collection — count list length |
| "business location / state" | Must be extracted from `description` text — there is no `state` column |
| "parking available" | `attributes.BusinessParking` or `attributes.BikeParking` in the `attributes` dict — check for truthy values |
| "WiFi available" | `attributes.WiFi` in `attributes` dict — value is a string: `"free"`, `"paid"`, or `"no"` |
| "accepts credit cards" | `attributes.BusinessAcceptsCreditCards = "True"` |

---

## googlelocal

| Term | Definition |
|---|---|
| "open business" | `state = 'OPEN'` in `business_description` (NOT a US state) |
| "US state" | Must be extracted from `description` text — `state` column is operating status |
| "business category" | Must be extracted from `description` text — there is no category column |

---

## stockmarket

| Term | Definition |
|---|---|
| "NYSE-listed stock" | `Listing Exchange = 'N'` (not 'A', not 'Q') |
| "NASDAQ stock" | `Listing Exchange = 'Q'` |
| "ETF" | `ETF = 'Y'` |
| "financially distressed" | `Financial Status` is 'D' (Deficient) or 'E' (Delinquent) or 'Q' (Bankrupt) |
| "normal financial status" | `Financial Status` is null, blank, or 'N' |
| "trading volume" | `Volume` column in the per-ticker DuckDB table |
| "price return" | (Close_end − Close_start) / Close_start |

---

## stockindex

| Term | Definition |
|---|---|
| "up day" | A trading day where Close > Open |
| "down day" | A trading day where Close < Open |
| "flat day" | A trading day where Close = Open (rare) |
| "average intraday volatility" | Mean of (High − Low) / Open across all days in the period |
| "Asia region" | Exchanges in: Japan, Hong Kong, China, South Korea, India, Australia, Singapore |
| "Europe region" | Exchanges in: UK, Germany, France, Switzerland, Netherlands, etc. |
| "North America region" | Exchanges in: USA and Canada |

---

## crmarenapro

| Term | Definition |
|---|---|
| "won deal" / "closed deal" | Opportunity with `StageName = 'Closed Won'` |
| "lost deal" | Opportunity with `StageName = 'Closed Lost'` |
| "active contract" | Contract with `Status = 'Activated'` |
| "converted lead" | Lead with `IsConverted = True` |
| "open case" / "support ticket" | Case with `Status` NOT in ('Closed', 'Resolved') |
| "revenue" | `Amount` column in the Opportunity table |
| "deal size" | `Amount` in Opportunity |
| "contract duration" | `ContractTerm` in months |
| "pipeline stage order" | Prospecting → Qualification → Needs Analysis → Value Proposition → Id. Decision Makers → Perception Analysis → Proposal/Price Quote → Negotiation/Review → Closed Won/Lost |

---

## agnews

| Term | Definition |
|---|---|
| "World news article" | Article whose title/description is about international politics, conflicts, diplomacy |
| "Sports article" | Article about sporting events, athletes, teams |
| "Business article" | Article about finance, markets, companies, economy |
| "Science/Technology article" | Article about science, technology, research, software |

---

## PATENTS

| Term | Definition |
|---|---|
| "patent family" | Group of patents linked by `family_id` — different national filings of the same invention |
| "PCT application" | International application under Patent Cooperation Treaty — `pct_number` is non-null |
| "utility patent" | `application_kind = 'utility patent application'` |
| "CPC class" | Cooperative Patent Classification code — hierarchical: Section → Class → Subclass → Group |
| "citation count" | Count of entries in `citation` field |
| "filing date" | Date the application was submitted to the patent office (`filing_date`) |
| "grant date" | Date the patent was officially granted (`grant_date`) — may be null if not yet granted |
| "prosecution duration" | grant_date − filing_date |

---

## PANCANCER_ATLAS

| Term | Definition |
|---|---|
| "LGG" | Brain Lower Grade Glioma |
| "BRCA" | Breast Invasive Carcinoma |
| "GBM" | Glioblastoma Multiforme |
| "LUAD" | Lung Adenocarcinoma |
| "LUSC" | Lung Squamous Cell Carcinoma |
| "gene expression" | Normalised RNA-seq count — use log10(count + 1) transformation before averaging |
| "mutation" | Entry in Mutation_Data table |
| "missense mutation" | `Variant_Classification = 'Missense_Mutation'` — amino acid change |
| "driver gene" | Commonly: TP53, EGFR, KRAS, CDH1, PIK3CA (contextual — agent should not assume) |
| "survival analysis" | Use `vital_status` and survival time columns from clinical_info |

---

## music_brainz_20k

| Term | Definition |
|---|---|
| "unique track" / "unique song" | Deduplicated entity — NOT a unique `track_id`. Group by (title, artist, album) with fuzzy matching |
| "total sales" | SUM of sale records, one row = one unit sold |
| "sales revenue" | NOT available — only unit count is in the sales table |

---

## DEPS_DEV_V1

| Term | Definition |
|---|---|
| "released version" | `VersionInfo.IsRelease = True` after JSON parsing |
| "has security advisory" | `Advisories` list is non-empty after parsing |
| "publication date" | `UpstreamPublishedAt` ÷ 1000 → Unix seconds → `datetime.fromtimestamp()` |
| "MIT-licensed" | `Licenses` array contains `"MIT"` after parsing |

---

## GITHUB_REPOS

| Term | Definition |
|---|---|
| "primary language" | Language with the highest byte count in `language_description` text |
| "watchers" | `watch_count` in the `repos` table |
| "open source license" | Any SPDX identifier in the `license` column: mit, apache-2.0, gpl-2.0, bsd-2-clause, etc. |
| "no license" | `license` is null or empty string |
