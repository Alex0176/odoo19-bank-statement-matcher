# Bank Statement Matcher

Assign imported bank statement lines to invoices, vendor bills, credit notes and
payments — on **Odoo 19 Community**.

## Why

Odoo's bank reconciliation widget is part of `account_accountant`, an
**Enterprise** module. On Community there is no way to assign an imported bank
line to a document from the user interface, even though the underlying
reconciliation API is present. Statement lines simply pile up on the bank
suspense account.

This module rebuilds the missing step: it proposes matches, lets you review and
correct them, and applies them through the regular accounting API.

## What it does

* **Suggests on import.** Every new statement line is searched against the open
  receivables and payables as soon as it is created.
* **Explains itself.** Each suggestion carries a confidence and the rule that
  produced it, so you can see *why* something was proposed.
* **Can be searched again, later.** This is the point: a line that matches
  nothing today usually becomes matchable once the vendor bill, the credit note
  or the down payment has been entered. "Search again" picks those up.
* **Assigns in bulk or one by one**, and lets you undo an assignment.
* **Refuses to guess.** Ties are never resolved automatically, and weak
  suggestions are shown but not booked.

## Matching rules

| Confidence | Rule | Meaning |
|-----------:|------|---------|
| 100 | `reference` | One of the document's own identifiers (number, reference, payment reference, source document) appears in the bank's free text. |
| 80 | `partner_amount` | The partner is known and the open amount matches to the cent. |
| 60 | `amount_unique` | The amount identifies exactly one open item. |
| 30 | `partner` | Same partner, different amount — a hint, not a match. |

The comparison always runs **document → bank text**, never the other way round.
Taking tokens out of the bank text and searching them with `%token%` looks
equivalent but floods the results: a four-digit token such as `0555` matches
`BNK1/2024/0555` and every other document containing those digits.

Nothing in the rules is country- or installation-specific, so any numbering
scheme works.

## Safety

Money is involved, so the module is deliberately cautious:

* Suggestions are **proposals only**. Nothing is ever booked without a user
  action.
* Each journal sets the confidence needed for the bulk action
  (default: reference, or partner *and* amount). Weaker matches must be
  confirmed individually.
* Stored suggestions are re-checked before use. A document settled in the
  meantime — by a colleague, or by the twin of a statement line that was
  imported twice — is refused rather than reconciled twice.
* Each line is assigned inside its own savepoint: one failure never leaves
  another line half-assigned.

## Usage

*Accounting → Accounting → Bank Line Assignment* lists everything still open.

* Select lines → *Assign Bank Lines* for the bulk review screen.
* Open a single line to see its suggestions and assign, change or undo one.
* Per journal: *Suggest matches on import* and *Assign automatically from*.

## Installation

Copy the folder into your addons path, update the app list and install
**Bank Statement Matcher**. Depends only on `account`.

Because Odoo 19 Community ships no form or list view for
`account.bank.statement.line`, this module brings its own rather than inheriting
views that may not exist.

## Tested with

Odoo 19.0 Community.

## License

AGPL-3. See `LICENSE`.
