---
description: Bootstrap skill for managing HPE ProLiant Gen8 and Gen9 servers through the iLO 4 RESTful (Redfish) API instead of the web UI. Read-only by default (discover, identity, inventory, health, logs, power status); power, virtual-media and boot-once actions run only with a recorded operator approval that names the action and the host. It builds one request and calls the iLO Redfish effect node CLI; it holds no credentials, addresses or Redfish logic. Smart Array and RAID changes are out of scope (SSA or ssacli). Replaced by an onex skill dispatch skill on node_ilo_redfish_effect when that node is hosted on the bus.
mode: full
version: 1.0.0
level: advanced
debug: false
category: infrastructure
bootstrap: true
skill_kind: methodology
tags:
  - ilo
  - redfish
  - hpe
  - server-management
  - bootstrap
author: omninode
---

# iLO Redfish (bootstrap)

This skill is a bootstrap skill. The logic is in the `node_ilo_redfish_effect` node in omnimarket; this skill is
the hand-run way to call it until an `onex skill` dispatch mapping exists for that node. It records and decides
nothing itself: the node refuses what is unsafe, and you relay its typed answer.

**Replaced by** an `onex skill` dispatch skill over `node_ilo_redfish_effect`, once the node declares a bus
command topic and a skill mapping entry. **Replace this skill with that dispatch skill when it lands.**

## What it does and does not do

- Targets **iLO 4** (HPE ProLiant Gen8 and Gen9, firmware 2.30 and later for Redfish 1.0 conformance; written for
  2.82). It does not assume iLO 5 behaviour. Anything the HPE documentation does not establish for a generation
  is discovered from the live resource tree and refused when absent, never guessed.
- Read verbs: `discover`, `identity`, `inventory`, `health`, `logs`, `power-status`. They change nothing.
- Write verbs: `power` (`on`, `force_off`, `force_restart`, `power_button`), `virtual-media` (`insert`, `eject`,
  CD or DVD ISO only), `boot-once` (`pxe`, `cd`, `hdd`, `usb`, `bios_setup`, `uefi_shell`).
- It has **no** verb for accounts, privileges, licenses, firmware, BIOS settings, network settings, certificates,
  log clearing or storage. **Smart Array and RAID configuration is not done here:** Gen9 RAID changes use HPE
  Smart Storage Administrator or its `ssacli` command line on the host, as a separate approved action.

## Setup (the operator, once per host)

1. **Read account.** In the iLO, create a local account with the **Login** privilege only. Put its user name and
   password in the lab secret store under `ILO_<HOST>_READ_USERNAME` and `ILO_<HOST>_READ_PASSWORD`, where
   `<HOST>` is the upper-cased host name (the template is the node contract's `credential_key_template`). Never
   put a credential in a file, an environment variable, a ticket or this chat.
2. **Pin the certificate.** The iLO presents a self-signed certificate. Fetch it once, compare its SHA-256
   fingerprint with the one the iLO shows on its certificate page or console, and only then save the PEM next to
   the overlay file and record the fingerprint. Verification is never turned off; a changed certificate makes the
   host refuse until the pin is updated.
3. **Overlay row.** In the private overlay `node_ilo_redfish_effect/overlay.yaml` (under a root listed in
   `ONEX_SKILL_OVERLAY_ROOTS`) add the host: `name` (the lab host name), `generation` (`gen8` or `gen9`),
   `address`, `expected_product`, `tls.ca_file` and `tls.sha256`, `media_url_prefixes` for any ISO server, and the
   top-level `journal_dir`. Leave `live: false` and `expected_serial` unset.
4. **Approve the first read.** Say so on the record, then set `live: true`. Run `discover` and `identity`, and copy
   the reported serial into `expected_serial`. Writes stay refused until the serial is set.
5. **Write account, only when the first write is approved.** Create a second local account with **Login, Virtual
   Power and Reset, Virtual Media** and nothing else (never Configure iLO Settings, Administer User Accounts or
   Remote Console), and store it under `ILO_<HOST>_WRITE_USERNAME` and `ILO_<HOST>_WRITE_PASSWORD`.

The node reads the secret store through the lane resolver (`ONEX_SECRET_RESOLVER_CONFIG_PATH`). A value that
would come from the process environment is refused.

## The command

Every call is this one command, from your omnimarket checkout:

```bash
cd "${OMNIBASE_PATH:?set OMNIBASE_PATH}/omnimarket" && env -u PYTHONPATH uv run python -m \
  omnimarket.nodes.node_ilo_redfish_effect.runtime_ilo_redfish_cli --verb <verb> --host <host> [options]
```

It prints one JSON result (`outcome`, `refusal`, `detail`, `data`, `evidence`, `idempotency_key`, `ledger_row`)
and exits 0 for `ok` or `noop`, 2 for a refusal, 3 for anything else. Show the JSON; do not paraphrase a refusal.

Read examples (`--requested-by` defaults to `$ONEX_LANE`):

```bash
... --verb identity --host <host>
... --verb power-status --host <host>
... --verb logs --host <host> --log-kind iml --log-limit 20
```

## Writes: approval first, then one run

A write needs a recorded operator approval. The agent never writes one for itself.

1. State the exact action and host to the operator, for example "force a restart of `<host>`" or "insert
   `<image url>` into the virtual CD of `<host>`".
2. The operator approves in the record: an OPERATOR-CONSENT row whose APPROVED SCOPE text carries the words
   `ilo-redfish`, `host=<host>` and `action=<action>` (`power:force_restart`, `power:on`, `power:force_off`,
   `power:power_button`, `virtual_media:insert` with `image=<url>`, `virtual_media:eject`, `boot_once:<target>`),
   and whose OUT OF SCOPE list is filled in. The row is good for 24 hours and for one execution.
3. Run the command with `--approval-ref <timestamp of that row>` and the verb options, for example
   `--verb power --host <host> --power-action force_restart --approval-ref <ts>`.
4. Append the result's `ledger_row` to the work ledger as a STATUS row (the ledger-write skill). It carries the
   requested action, the approval reference, the outcome and the verification evidence, and no credential.

The node checks, in order and before sending anything: the approval row (action, host, approver, age, not
self-approved), the live serial and product against the overlay, the journal for an earlier attempt, and the
current state (a server already in the requested state is a `noop`). After sending it reads the state back.

## Retries

One approval authorizes one execution, tracked by the `idempotency_key`. If a run ends `unknown` (connection
lost, timeout, a server error) or `unverified`, **do not run it again**: the change may have happened. Run
`power-status` (or the matching read), report what it shows, and ask for a new approval if a repeat is still
wanted. A repeat of the same request returns `already_attempted` and sends nothing. Only a rejected attempt
(`failed`, for example a missing privilege) may be retried with the same approval after the cause is fixed.

## Refusals you will see

`host_not_live`, `credential_missing`, `tls_failed` (do not weaken anything; fix the pin or the iLO's TLS
settings), `approval_missing`, `approval_invalid`, `identity_unconfirmed`, `identity_mismatch` (stop: this may
not be the server the operator means), `endpoint_missing` (this generation does not advertise it; do not work
around it), `precondition_failed`, `media_url_not_allowed`, `insufficient_privilege` (report it; never widen an
account yourself).
