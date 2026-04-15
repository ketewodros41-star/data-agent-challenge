# Unstructured Field Inventory

Fields that contain structured data stored as text, natural language, HTML, or JSON strings.
The agent must extract before computing. Listed by dataset.

---

## yelp

| Field | Table/Collection | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `description` | business (MongoDB) | yelp_db | NL text with embedded location (city, state, address) | Regex or LLM extraction for state/city |
| `attributes` | business (MongoDB) | yelp_db | Python dict serialised as string (or null) | `ast.literal_eval()` then key lookup |
| `hours` | business (MongoDB) | yelp_db | Python dict of day→hours string | `ast.literal_eval()` |
| `elite` | user (DuckDB) | user_database | Comma-separated year strings, e.g. "2015,2016" | Split on comma, cast to int |
| `text` | review/tip (DuckDB) | user_database | Free text — sentiment/topic extraction needed for some queries | LLM or keyword search |
| `date` (checkin) | checkin (MongoDB) | yelp_db | List of ISO timestamp strings | Parse each element |

---

## googlelocal

| Field | Table | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `description` | business_description (PostgreSQL) | googlelocal_db | NL text with business category, address, US state | Regex for state abbreviation; LLM for category |
| `MISC` | business_description (PostgreSQL) | googlelocal_db | JSON-like dict of amenities/attributes | `json.loads()` or `ast.literal_eval()` |
| `hours` | business_description (PostgreSQL) | googlelocal_db | List of operating hour strings | Parse each element |
| `text` | review (SQLite) | review_database | Free text review — sentiment queries possible | LLM or keyword extraction |

**Important:** `state` column in `business_description` is *operating status* (OPEN/CLOSED), NOT a US state. US state must come from `description` text.

---

## agnews

| Field | Collection/Table | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `title` + `description` | articles (MongoDB) | articles_db | Free text — **category must be inferred from these** | LLM classification into: World / Sports / Business / Science/Technology |

**Category inference prompt:** "Given this news article title and description, classify it into exactly one of: World, Sports, Business, Science/Technology."

---

## bookreview

| Field | Table | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `description` | books_info (PostgreSQL) | bookreview_db | String repr of Python list, e.g. `"['Great book', 'A must read']"` | `ast.literal_eval()` then join list |
| `categories` | books_info (PostgreSQL) | bookreview_db | String repr of Python list, e.g. `"['Books', 'Mystery']"` | `ast.literal_eval()` |
| `features` | books_info (PostgreSQL) | bookreview_db | String repr of dict or list | `ast.literal_eval()` |
| `details` | books_info (PostgreSQL) | bookreview_db | String repr of dict with publisher, ISBN, etc. | `ast.literal_eval()` then key lookup |

---

## PATENTS

| Field | Table | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `Patents_info` | publicationinfo (SQLite) | publication_database | NL summary containing application_number, publication_number, assignee_harmonized, country_code | Regex extraction: e.g. `r'publication number[:\s]+([A-Z0-9]+)'` |
| `publication_date` | publicationinfo | publication_database | NL date string, e.g. "March 15th, 2020" | `dateparser.parse()` or `datetime.strptime` with multiple formats |
| `filing_date` | publicationinfo | publication_database | NL date string | Same as above |
| `grant_date` | publicationinfo | publication_database | NL date string | Same as above |
| `priority_date` | publicationinfo | publication_database | NL date string | Same as above |
| `claims_localized_html` | publicationinfo | publication_database | HTML text | `BeautifulSoup.get_text()` before NLP |
| `description_localized_html` | publicationinfo | publication_database | HTML text | `BeautifulSoup.get_text()` before NLP |
| `cpc` | publicationinfo | publication_database | CPC classification code(s) as string | Split on delimiter; join to cpc_definition |

**Date parsing priority:** try `"%B %dth, %Y"`, `"%B %dst, %Y"`, `"%B %dnd, %Y"`, `"%B %drd, %Y"`, then `dateparser.parse()` as fallback.

---

## DEPS_DEV_V1

| Field | Table | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `Licenses` | packageinfo (SQLite) | package_database | JSON-like array string | `json.loads()` |
| `Links` | packageinfo | package_database | JSON-like list of {type, url} objects | `json.loads()` |
| `Advisories` | packageinfo | package_database | JSON-like list | `json.loads()` |
| `VersionInfo` | packageinfo | package_database | JSON-like object with IsRelease, Ordinal | `json.loads()` |
| `Registries` | packageinfo | package_database | JSON-like list | `json.loads()` |
| `UpstreamIdentifiers` | packageinfo | package_database | JSON-like list | `json.loads()` |
| `UpstreamPublishedAt` | packageinfo | package_database | Unix timestamp in **milliseconds** | Divide by 1000 for seconds; then `datetime.fromtimestamp()` |
| `Project_Information` | project_info | project_database | NL text with GitHub stars, forks, description | Regex: `r'stars[:\s]+(\d+)'`, `r'forks[:\s]+(\d+)'` |

---

## GITHUB_REPOS

| Field | Table | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `language_description` | languages (SQLite) | metadata_database | NL text listing languages with byte counts | Regex: `r'(\w[\w\s]+):\s*(\d+)\s*bytes'`; primary language = highest byte count |
| `repo_data_description` | contents (DuckDB) | artifacts_database | NL metadata describing file attributes | Regex or keyword extraction for size, binary, mode |

---

## PANCANCER_ATLAS

| Field | Table | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `Patient_description` | clinical_info (PostgreSQL) | pancancer_clinical | NL text embedding barcode, UUID, gender, vital status | Regex: `r'TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}'` for barcode |

---

## crmarenapro

| Field | Table | DB | Content type | Extraction approach |
|---|---|---|---|---|
| `Description` | Account/Opportunity/Contract (SQLite/DuckDB) | various | Free text business description | Keyword or LLM extraction |
| `Subject`/`Description` | Case/CaseComment | support_tickets | Free text ticket content — sentiment/issue type queries | LLM classification |
| Email `Body` | EmailMessage | email_database | Free text email — intent/topic classification | LLM |

---

## Summary: extraction library to import

```python
import ast          # for Python-repr strings
import json         # for JSON strings
import re           # for regex extraction
import dateparser   # for natural language dates (pip install dateparser)
from bs4 import BeautifulSoup  # for HTML fields (pip install beautifulsoup4)
from rapidfuzz import fuzz     # for fuzzy string matching (pip install rapidfuzz)
```
