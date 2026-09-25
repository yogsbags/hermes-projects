---
name: aveyroni-relationship-map
description: "Use when mapping owners, advisers, and a path in."
version: 1.0.0
author: Aveyroni
license: MIT
metadata:
  hermes:
    tags: [relationships, outreach, promoters, origination]
    related_skills: [aveyroni-ownership, evidence, origination-controller]
---

# Relationship map

Map people and institutions already tied to one priority company. This is not permission to contact them.

## Screening pass

On a team screening pass, stop early.

1. One web_search per company.
2. If the snippet names a person and a role, record that claim and do not web_extract.
3. Return at most the owner, promoter, or founder, and one other named person. Use the terms that apply in the target's jurisdiction.
4. One unknown covers a missing adviser, auditor, lender, or equivalent governance contact. Do not list each missing role.
5. Do not write an outreach brief.

## Nodes

A full map, only when the user asks for one and no screening name list was given. Look, in order, for: owner, promoter, or founder; CEO or managing director if different; board; jurisdiction-appropriate governance contact; external auditor; named lender; sell-side or buy-side adviser; industry association; and any person already in Aveyroni's contact notes.

A node needs a name, a role, a source, and evidence ids. "The founder" is not a node. If the leadership page names a title and no person, record the title as unverified and do not invent a name.

## Path in

If an Aveyroni or client contact shares an evidenced link with a node, record the path as `contact → node → company`. If none exists, write `no warm path found`. Do not suggest a mutual acquaintance from a shared city, college, or sector.

## Outreach brief

Not part of a screening pass. When the user asks for a full map, four to six sentences the user could edit later:

1. Who the legal entity is.
2. One sourced reason it fits the mandate.
3. The transaction status in the status's own words, including that no public process is not an off-market proof.
4. The ask is a conversation, not a process. Do not claim the owner wants to sell.

Done when every named person has a source, and no email is sent. Drafts wait for the user.
## Inputs

A resolved entity and sources that name people or advisers.

## Outputs

Claim field relationship: person or firm, role, URL, and excerpt. No message draft.

## Workflow

1. Extract named people and advisers from sourced pages.
2. Keep the relationship unknown when the page does not name them.
3. Stop before any email, call, or introduction.

## Rules

Mapping is not outreach. Do not invent a warm introduction.

## Failure conditions

Stop when the user asks to send a message. Return no relationship when the only hit is an unsourced directory guess.

## Examples

A rating report names a promoter. Record the name and the report URL. Do not draft a note to that person. Format example only.
