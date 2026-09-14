# Odoo 19 — Bank Statement Matcher

Assign imported bank statement lines to invoices, vendor bills, credit notes and
payments on **Odoo 19 Community**.

| Module | Purpose |
|---|---|
| `account_statement_matcher` | The matcher itself. Depends on `account` only. |
| `account_statement_matcher_import_oca` | Optional bridge: after an OCA statement import, go straight to the assignment screen. Installs itself when both sides are present. |

## Why

Odoo's bank reconciliation widget is part of `account_accountant`, an
**Enterprise** module. On Community there is no way to assign an imported bank
line to a document from the user interface, even though the underlying
reconciliation API is present. Statement lines simply pile up on the bank
suspense account.

This module rebuilds the missing step: it proposes matches, lets you review and
correct them, and applies them through the regular accounting API
(`account.move.line.reconcile`).

## What it does

* **Suggests on import.** Every new statement line is searched against the open
  receivables and payables as soon as it is created.
* **Explains itself.** Each suggestion carries a confidence and the rule that
  produced it, so you can see *why* something was proposed.
* **Can be searched again, later.** This is the point: a line that matches
  nothing today usually becomes matchable once the vendor bill, the credit note
  or the down payment has been entered. *Search again* picks those up.
* **Says something useful when it cannot match.** A payment quoting a quotation
  that was never invoiced gets a note naming that quotation, instead of a bare
  "no match" — somebody still has to raise the invoice.
* **Lets you assign by hand.** A picker over every open item, for everything the
  search cannot know about.
* **Assigns in bulk or one by one**, and lets you undo an assignment.
* **Refuses to guess.** Ties are never resolved automatically, and weak
  suggestions are shown but not booked.

## Matching rules

| Confidence | Rule | Meaning |
| --- | --- | --- |
| 100 | `reference` | One of the document's own identifiers (number, reference, payment reference, source document) appears in the bank's free text. |
| 80 | `partner_amount` | The partner is known and the open amount matches to the cent. |
| 60 | `amount_unique` | The amount identifies exactly one open item. |
| 30 | `partner` | Same partner, different amount — a hint, not a match. |

Two details decide whether this works in practice:

**The comparison runs document → bank text, never the reverse.** Taking tokens
out of the bank text and searching them with `%token%` looks equivalent but
floods the results: a four-digit token such as `0555` matches `BNK1/2024/0555`
and every other document containing those digits.

**References arrive glued to other text.** Banks send things like
`999BE10154Bauer Thomas`. Splitting only at separators finds nothing, so the
tokeniser also splits at digit/letter boundaries and rejoins neighbouring pieces,
which recovers the `BE10154` in the middle.

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
* Journal items carrying no date at all are kept out of the suggestions and
  refused on assignment. Such rows exist in migrated databases and make Odoo's
  reconciliation engine raise a `TypeError`, because it sorts by
  `date_maturity or date`.

## Usage

*Accounting → Accounting → Bank Line Assignment* lists everything still open.

* Select lines → *Assign Bank Lines* for the bulk review screen.
* Open a single line to see its suggestions, assign one, pick a document by
  hand, or undo an assignment.
* Select statements in the statement list → *Assign Bank Lines* to work through
  one statement.
* Per journal: *Suggest matches on import* and *Assign automatically from*.

With `account_statement_matcher_import_oca` installed, importing a statement
file lands on the assignment screen directly, filtered to the new lines.

## Installation

Copy the folders into your addons path, update the app list and install
**Bank Statement Matcher**. The bridge installs itself if the OCA importer
([`odoo19-bank-statement-import`](https://github.com/Alex0176/odoo19-bank-statement-import))
is present.

Because Odoo 19 Community ships no form or list view for
`account.bank.statement.line`, this module brings its own rather than inheriting
views that may not exist.

## Notes for other Odoo versions

Written and tested against **Odoo 19.0 Community**. Two things would need
checking before using it elsewhere: `_seek_for_lines()` on
`account.bank.statement.line`, which splits a statement move into its liquidity,
suspense and remaining items, and the fact that after rewriting the counterpart
the line is reported as an "other" item rather than a suspense one — reconciling
only the suspense bucket is a silent no-op.

## Translations

English source, German included (`i18n/de.po`).

## License

AGPL-3. See `LICENSE`.
