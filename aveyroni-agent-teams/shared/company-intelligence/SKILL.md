---
name: company-intelligence
description: "Use when profiling products, plants, customers, exports, or revenue."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [company-profile, manufacturing, financials, origination]
    related_skills: [research, evidence, tavily, aveyroni-fit-score]
---

# Company profile

Build the profile from evidence records. Leave a field empty rather than guessing a plausible manufacturer.

## Fields

| Field | Accept | Reject |
| --- | --- | --- |
| Products | Named processes or parts from the site or a rating report | "auto components" copied from the mandate |
| Plants | City plus site or report | A headquarters city treated as a plant |
| Customers | Named OEM or Tier-1, or "names not disclosed" if that is what the source says | Implied customers from the end market |
| Exports | Destination tied to this legal entity | A group company's exports |
| Revenue | A reported range in ₹ crore, with year and source | A point estimate presented as fact |
| EBITDA | Reported figure, or the string `unknown` | A margin borrowed from comps |

## Revenue

If the source gives a year and a number, store low and high. A single reported number can be both bounds. If you only have a band from a directory, confidence is `low`. If you have nothing, set low and high to null and confidence to `unknown`. Never back into revenue from headcount, plant count, or export awards.

Comps may show where peers sit. They do not assign this company a revenue or EBITDA.

## Completion

The profile matches `schemas/company.json` for the fields this skill owns. Every non-empty field has evidence ids. `seller_interest` is not set here.
