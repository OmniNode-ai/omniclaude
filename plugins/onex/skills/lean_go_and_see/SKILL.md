---
description: Prose stand-in for go and see, genchi genbutsu. Read the live surface and not the account of it; every ruling carries a live check or is marked one-time. Replaced by plan tasks T-P4 and T-L2; delete this skill when they land.
mode: full
version: 1.0.0
level: basic
debug: false
category: process
tags:
  - lean
  - go-and-see
  - verification
  - prose-stand-in
author: omninode
---

# Lean Go and See (prose stand-in)

This skill is a prose stand-in. It checks nothing for you. It asks you to read the
live surface by hand before you report on it.

**Replaced by** the lean practices plan: T-P4 (a `live-check=` cell on
every ruling at intake, refused by the typed ledger append when absent, and a drift
check on a schedule) and T-L2 (the evidence reference resolver, which makes a
chain's evidence a lookup). **Delete this skill when T-P4 is merged and deployed.**

## When to use

Before you state that something is running, merged, deployed, fixed, drifted or
done; before you record a ruling; before you trust a brief's account of state.

## The rule

Read the live surface, not the account of it. A summary, a ledger row, a memory
note or a ticket status says what someone saw at one time. The live state says what
is true now. Report the live reading with the command that took it and the time.

## Procedure

1. **Name the surface.** What exactly governs the claim: a pull request head on the
   remote, a process on a host, a deployed tag, a config value, a check-run.
2. **Read it yourself.** Use the narrowest command that returns the state. Read the
   check-runs for a head and not a rollup; read the remote default branch and not a
   stale local copy.
3. **Classify the result.**
   - **MATCH**: the live state agrees with the claim.
   - **DRIFTED**: it disagrees. Say how, and open an andon stop if it is a class
     (`lean_andon_stop`).
   - **UNREADABLE**: you cannot read it. Say so. Never report UNREADABLE as MATCH.
4. **Report with provenance.** The claim, the command, the output and the read time.
5. **Give new rulings a live check.** When you record a ruling, write the command
   that reads the state it governs, as a `live-check=` cell. If it governs a
   one-time decision with nothing to read afterwards, mark it so. A ruling with
   neither cannot be audited later, and that is the largest gap the plan found:
   most recorded rulings were unreadable.

## Common traps

- Reporting from the ledger what only the live surface can show.
- Reading a local clone that is behind the remote.
- Reading a green rollup while a required context is missing or stale.
- Treating "I fixed it" as "it reads fixed".

## What this skill cannot do

It cannot make a ruling auditable after the fact, and it cannot run the drift check.
Until T-P4 lands, the audit of the existing rulings is a manual read.
