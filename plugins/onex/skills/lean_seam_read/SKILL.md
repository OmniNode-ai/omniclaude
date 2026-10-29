---
description: Bootstrap skill for the seam reading. Read the crossings at a seam between two stations and count those that do not match the canonical shape. Replaced by its node-backed skill on node_seam_reading_compute; replace it when that lands.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
bootstrap: true
skill_kind: methodology
tags:
  - lean
  - seam
  - verification
  - bootstrap
author: omninode
---

# Lean Seam Read (bootstrap)

This skill is a bootstrap skill. It is the hand-run form of the practice, kept so lanes can test and
iterate on the process while the real mechanism is built; it is a tool to make tools. It counts
nothing for you: it asks you to read the crossings by hand and count the ones that do not match the
shape both sides agreed on. It is replaced by its node-backed skill when that skill comes online.

**Replaced by** the node-backed seam-read skill on `node_seam_read_orchestrator` and `node_seam_reading_compute`
(plan task T-S1: the factory line graph contract, the seam reading record and the verdict line; the nodes are
merged in omnimarket, the skill that calls them is not built). **Replace this skill with the node-backed skill when it
lands.**

## The practice

A seam is the place where one station hands work to the next: a brief to a lane, a
lane to a pull request, a pull request to the landing controller. Defects collect at
seams because each side checks only its own half. Read what actually crossed, not
what either side says it sent, and count the crossings that do not match the
canonical shape.

## When to use

When a station reports success and the next one stalls or refuses; when a class of
defect shows up twice at the same hand-off; before you open an andon stop on a seam
mismatch (`lean_andon_stop`).

## Steps by hand today

1. **Name the seam.** The two stations and the kind of thing that crosses.
2. **Write down the canonical shape.** The fields or properties a crossing must
   carry, taken from the contract or the receiving side's checker, not from memory.
3. **Take the crossings.** The last several (the plan proposes twenty) that
   crossed, read from the live surface (`lean_go_and_see`), with the read time.
4. **Compare each to the shape.** Count crossings that match, crossings that do not,
   and crossings you could not read. Never count an unreadable crossing as a match.
5. **Report the reading.** The seam, the shape, the counts, the command and the read
   time. A nonzero mismatch count on a known class opens a stop.

## Factory task per step

Each step above is replaced by this task of the lean practices plan.

| Step | Factory task |
| -- | -- |
| 1 | T-S1 (factory line graph contract) |
| 2 | T-S1 (factory line graph contract) |
| 3 | T-S1 (seam reading record) |
| 4 | T-S1 (seam reading record) |
| 5 | T-S1 (verdict line) |

## What this skill cannot do

It cannot make the two sides agree on a shape, and it cannot read for you. If you do
not take the reading, nothing does.
