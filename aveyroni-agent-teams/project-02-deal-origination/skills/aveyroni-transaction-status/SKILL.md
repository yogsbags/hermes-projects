---
name: aveyroni-transaction-status
description: "Use when classifying whether a company is already in a deal."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [transaction-status, off-market, private-equity, origination]
    related_skills: [aveyroni-ownership, evidence]
---

# Transaction status

Assign exactly one status from `schemas/screening.json`. Search the legal name plus: acquired, acquisition, "private equity", investment, funding, "strategic review", "mandated", sale, divest.

## Statuses

| Status | Use only when |
| --- | --- |
| `CONFIRMED_OWNER_DIALOGUE` | The client or a named adviser source says talks are underway |
| `ACTIVE_SALE_PROCESS` | A named banker mandate, teaser, or CIM is in the sources |
| `FUNDRAISING` | A current round or capital raise is reported, with the round named |
| `RECENTLY_ACQUIRED` | A closed acquisition of this legal entity, with buyer and date |
| `PE_BACKED` | Named institutional PE ownership or control |
| `STRATEGICALLY_OWNED` | A corporate parent controls the entity |
| `NO_PUBLIC_PROCESS_FOUND` | The searches above ran and none of the stronger statuses were supported |
| `UNKNOWN` | Search did not run, or the entity is unresolved |

## Hard rule

`NO_PUBLIC_PROCESS_FOUND` is not proof the company is off-market. Write that sentence in `transaction_status_note`. Do not use the words "confirmed off-market" or "proprietary deal" for this status.

## Completion

The status, the note, the queries run, and the evidence ids are saved. A news story about a different group company does not set the status. If two statuses both have evidence, keep the more specific one and put the other in the note.

## Common pitfalls

1. Upgrading "no article found" into off-market.
2. Using a competitor's transaction as this company's status.
## Inputs

A resolved entity and the pages that mention a sale, a fundraise, an acquisition, or the absence of those.

## Outputs

One status from the screening schema: UNKNOWN, NO_PUBLIC_PROCESS_FOUND, PE_BACKED, STRATEGICALLY_OWNED, RECENTLY_ACQUIRED, FUNDRAISING, ACTIVE_SALE_PROCESS, or CONFIRMED_OWNER_DIALOGUE. Plus a note.

## Workflow

1. Search for a process.
2. Map a listing or pending sale to ACTIVE_SALE_PROCESS.
3. If no process is in the pages you opened, use NO_PUBLIC_PROCESS_FOUND and say that is not proof the target is off-market.

## Rules

Transaction status records sourced process or ownership facts. Do not infer availability from silence.

## Failure conditions

Unknown when the pages fail to load. Do not write NO_PUBLIC_PROCESS_FOUND from memory of an empty search you did not run.

## Examples

Excerpt "Active listing" sets ACTIVE_SALE_PROCESS. The note says it is not owner intent. Format example only.
