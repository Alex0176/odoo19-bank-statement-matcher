# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
"""Matching of bank statement lines against open receivables and payables.

Why this module exists
----------------------
Odoo's bank reconciliation widget lives in ``account_accountant``, which is an
Enterprise module.  On Community there is therefore no way to assign an imported
bank statement line to an invoice from the user interface, even though the
underlying reconciliation API (``account.move.line.reconcile``) is present.

This module rebuilds the missing step: it proposes matches, lets a user review
and correct them, and applies them through the regular accounting API.

Design notes
------------
* Matching never looks at anything installation specific.  Candidates are found
  by comparing the *document's own* identifiers against the free text of the
  statement line, so the module works with any numbering scheme in any country.
* Candidates are stored rather than recomputed on every read.  A statement line
  that could not be matched at import time is expected to become matchable later
  -- when the vendor bill, the credit note or the down payment is finally
  entered -- so the suggestions have to be refreshable on demand.
* Applying a match is deliberately conservative: it refuses to act on anything
  that is already reconciled, and it never guesses between equally scored
  candidates.
"""

import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)

# Tokens shorter than this are too generic to identify a document.
MIN_TOKEN_LENGTH = 4
# Upper bound for the OR-search built from the statement text.
MAX_TOKENS = 25

SCORE_REFERENCE = 100
SCORE_PARTNER_EXACT = 80
SCORE_AMOUNT_UNIQUE = 60
SCORE_PARTNER_ONLY = 30


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    matcher_candidate_ids = fields.One2many(
        comodel_name="account.statement.match.candidate",
        inverse_name="statement_line_id",
        string="Match Suggestions",
        readonly=True,
    )
    matcher_state = fields.Selection(
        selection=[
            ("todo", "Not searched yet"),
            ("none", "No match found"),
            ("suggested", "Suggestion available"),
            ("ambiguous", "Several equal matches"),
            ("done", "Assigned"),
        ],
        string="Matching",
        default="todo",
        copy=False,
        index=True,
        help="Result of the last search for matching documents. Refresh it "
             "whenever new documents have been entered.",
    )
    matcher_candidate_count = fields.Integer(
        string="Suggestions",
        compute="_compute_matcher_candidate_count",
    )
    matcher_manual_line_id = fields.Many2one(
        comodel_name="account.move.line",
        string="Assign manually",
        copy=False,
        domain="[('reconciled', '=', False),"
               " ('account_id.reconcile', '=', True),"
               " ('account_id.account_type', 'in',"
               "  ('asset_receivable', 'liability_payable')),"
               " ('parent_state', '=', 'posted'),"
               " ('company_id', '=', company_id)]",
        help="Pick any open item yourself when no suggestion fits, for example "
             "when the payment belongs to a document the search cannot know "
             "about.",
    )
    matcher_hint = fields.Text(
        string="Note",
        readonly=True,
        copy=False,
        help="What the search found out about this line even though nothing "
             "could be assigned -- typically a quotation or an order that has "
             "not been invoiced yet.",
    )

    @api.depends("matcher_candidate_ids")
    def _compute_matcher_candidate_count(self):
        for line in self:
            line.matcher_candidate_count = len(line.matcher_candidate_ids)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _matcher_text(self):
        """Everything a bank sends us that could carry a document reference."""
        self.ensure_one()
        parts = [
            self.payment_ref or "",
            self.ref or "",
            self.narration or "",
            self.partner_name or "",
        ]
        return " ".join(parts)

    @api.model
    def _matcher_tokens(self, text):
        """Split bank free text into tokens that may be document references.

        Bank references arrive in every imaginable shape -- ``Re 1003515``,
        ``RG-2026/0042``, ``INV/2026/00017`` -- so the text is cut at every
        character that is neither a letter nor a digit, and the pieces are
        offered to the database as search terms.  Purely numeric noise such as
        dates is not filtered here on purpose: a wrong token simply finds
        nothing.
        """
        tokens = []

        def add(value):
            value = (value or "").lower()
            if len(value) >= MIN_TOKEN_LENGTH and value not in tokens:
                tokens.append(value)

        for chunk in re.split(r"[^0-9A-Za-z]+", text or ""):
            add(chunk)
            # Banks often send references glued to other text, as in
            # "999BE10154Bauer". Splitting at every digit/letter boundary and
            # re-joining neighbouring pieces recovers the "BE10154" in the
            # middle, which plain whitespace splitting never finds.
            pieces = re.findall(r"\d+|[A-Za-z]+", chunk)
            for index, piece in enumerate(pieces):
                add(piece)
                if index + 1 < len(pieces):
                    add(piece + pieces[index + 1])
        return tokens[:MAX_TOKENS]

    def _matcher_open_line_domain(self):
        """Open receivable/payable items that could settle this statement line.

        The sign decides the direction: money coming in settles a receivable,
        money going out settles a payable.  Both directions also cover credit
        notes and payments, because those post to the very same accounts.
        """
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("parent_state", "=", "posted"),
            ("reconciled", "=", False),
            ("account_id.reconcile", "=", True),
            ("account_id.account_type", "in",
             ("asset_receivable", "liability_payable")),
            ("statement_line_id", "=", False),
            # Odoo sorts a reconciliation by "date_maturity or date". An item
            # carrying neither makes that expression return False and the
            # reconciliation engine raises a TypeError comparing False to a
            # date. Such rows exist in databases migrated from older versions,
            # so they are kept out of the suggestions entirely.
            ("date", "!=", False),
        ]
        if self.amount > 0:
            domain.append(("balance", ">", 0))
        else:
            domain.append(("balance", "<", 0))
        return domain

    @api.model
    def _matcher_normalise(self, text):
        """Reduce text to letters and digits, so that formatting stops mattering.

        ``INV/2026/00017``, ``INV 2026 00017`` and ``inv-2026-00017`` all become
        ``inv202600017`` and therefore compare equal.
        """
        return re.sub(r"[^0-9a-z]", "", (text or "").lower())

    def _matcher_reference_hit(self, move, haystack):
        """True when one of the document's own identifiers is in the bank text.

        The comparison runs document -> text, never the other way round. Taking
        tokens from the bank text and searching for them with ``%token%`` looks
        equivalent but is not: a four digit token such as ``0555`` matches
        ``BNK1/2024/0555`` and floods the suggestions with unrelated documents.
        """
        for value in (move.name, move.ref, move.payment_reference,
                      move.invoice_origin):
            needle = self._matcher_normalise(value)
            if len(needle) >= MIN_TOKEN_LENGTH + 1 and needle in haystack:
                return True
        return False

    def _matcher_search(self):
        """Return ``{account.move.line: (score, rule)}`` for this line.

        Two stages on purpose: a cheap database funnel that errs on the side of
        collecting too much, then strict scoring in Python. Doing the scoring in
        SQL would mean loose ``ilike`` matching, which produces false positives.
        """
        self.ensure_one()
        AML = self.env["account.move.line"]
        base_domain = self._matcher_open_line_domain()
        precision = self.company_id.currency_id.rounding
        target = abs(self.amount)
        haystack = self._matcher_normalise(self._matcher_text())
        partner = self.partner_id.commercial_partner_id

        # --- Stage 1: funnel -------------------------------------------------
        pool = AML.browse()
        tokens = self._matcher_tokens(self._matcher_text())
        if tokens:
            ref_domain = []
            for field in ("move_id.name", "move_id.ref",
                          "move_id.payment_reference", "move_id.invoice_origin"):
                for token in tokens:
                    ref_domain.append((field, "ilike", token))
            ref_domain = ["|"] * (len(ref_domain) - 1) + ref_domain
            pool |= AML.search(base_domain + ref_domain, limit=200)
        if partner:
            pool |= AML.search(
                base_domain + [("partner_id", "child_of", partner.id)], limit=200)
        pool |= AML.search(base_domain, limit=400).filtered(
            lambda a: float_is_zero(abs(a.amount_residual) - target,
                                    precision_rounding=precision))

        # --- Stage 2: scoring ------------------------------------------------
        found = {}

        def remember(aml, score, rule):
            if aml not in found or found[aml][0] < score:
                found[aml] = (score, rule)

        amount_hits = AML.browse()
        for aml in pool:
            amount_ok = float_is_zero(abs(aml.amount_residual) - target,
                                      precision_rounding=precision)
            if amount_ok:
                amount_hits |= aml
            partner_ok = partner and aml.partner_id.commercial_partner_id == partner
            if self._matcher_reference_hit(aml.move_id, haystack):
                remember(aml, SCORE_REFERENCE, "reference")
            elif partner_ok and amount_ok:
                remember(aml, SCORE_PARTNER_EXACT, "partner_amount")
            elif partner_ok:
                remember(aml, SCORE_PARTNER_ONLY, "partner")

        # The amount on its own is only telling when it is unambiguous.
        if len(amount_hits) == 1 and amount_hits not in found:
            remember(amount_hits, SCORE_AMOUNT_UNIQUE, "amount_unique")

        return found

    def _matcher_documents_without_open_item(self, haystack):
        """Explain a line that names a document which cannot be settled yet.

        A customer paying against a quotation is the common case: the money is
        there, the invoice is not, so there is no open item to reconcile. Saying
        so is far more useful than reporting "no match" -- somebody still has to
        create the invoice.

        Sale and purchase are optional: the module depends on ``account`` only,
        so the models are looked up at runtime instead of being declared.
        """
        self.ensure_one()
        tokens = self._matcher_tokens(self._matcher_text())
        if not tokens:
            return ""
        notes = []
        # Labels are translated here, not stored as plain strings: passing an
        # untranslated word into a translated sentence leaves it in English.
        for model, label, number_field in (
            ("sale.order", _("Quotation/Order"), "name"),
            ("purchase.order", _("Purchase Order"), "name"),
        ):
            if model not in self.env:
                continue
            # Same funnel as for open items: let the database narrow it down
            # with a loose match, then verify strictly in Python.
            domain = ["|"] * (len(tokens) - 1) + [
                (number_field, "ilike", token) for token in tokens
            ]
            records = self.env[model].search(
                [("company_id", "=", self.company_id.id),
                 ("state", "not in", ("cancel",))] + domain, limit=20)
            for record in records:
                needle = self._matcher_normalise(record[number_field])
                if len(needle) >= MIN_TOKEN_LENGTH + 1 and needle in haystack:
                    notes.append(_(
                        "%(label)s %(name)s (%(partner)s, %(amount)s) matches this "
                        "payment but has no open item yet -- it is probably not "
                        "invoiced.",
                        label=label, name=record.display_name,
                        partner=record.partner_id.display_name,
                        amount=record.amount_total,
                    ))
        return "\n".join(notes)

    def action_matcher_assign_manual(self):
        """Assign the open item the user picked by hand."""
        for line in self:
            if not line.matcher_manual_line_id:
                raise UserError(_("Pick an open item first."))
            line._matcher_apply(line.matcher_manual_line_id)
            line.matcher_manual_line_id = False
        return True

    def action_matcher_refresh(self):
        """(Re-)search matching documents for the selected statement lines.

        Meant to be run again later: a line that found nothing at import time
        often becomes matchable once the corresponding bill, credit note or
        down payment has been entered.
        """
        Candidate = self.env["account.statement.match.candidate"]
        for line in self:
            line.matcher_candidate_ids.unlink()
            if line.is_reconciled:
                line.matcher_state = "done"
                continue
            found = line._matcher_search()
            if not found:
                # Nothing to reconcile -- but the line may still name a document.
                haystack = line._matcher_normalise(line._matcher_text())
                line.matcher_hint = line._matcher_documents_without_open_item(haystack)
                line.matcher_state = "none"
                continue
            line.matcher_hint = False
            values = []
            for aml, (score, rule) in found.items():
                values.append({
                    "statement_line_id": line.id,
                    "move_line_id": aml.id,
                    "score": score,
                    "rule": rule,
                })
            Candidate.create(values)
            best = max(found.values())[0]
            top = [aml for aml, (score, _r) in found.items() if score == best]
            line.matcher_state = "ambiguous" if len(top) > 1 and best < SCORE_REFERENCE \
                else "suggested"
        return True

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def _matcher_counterpart_lines(self):
        """The suspense line of this statement line, via the supported helper."""
        self.ensure_one()
        _liquidity, suspense, _other = self._seek_for_lines()
        return suspense

    def _matcher_apply(self, target_lines):
        """Book this statement line against ``target_lines`` and reconcile.

        Community has no API to set a counterpart on a statement line, so the
        suspense line is rewritten to the account of the document being settled
        and the two items are then reconciled the ordinary way.  The move has to
        leave the posted state for that, which is why everything happens inside
        one transaction: either the whole assignment succeeds or none of it does.
        """
        self.ensure_one()
        if self.is_reconciled:
            raise UserError(_("Statement line %s is already assigned.", self.display_name))
        if not target_lines:
            raise UserError(_("No document selected for %s.", self.display_name))
        # Suggestions are stored, so they can be stale: the document may have
        # been settled in the meantime -- by a colleague, or by the twin of a
        # statement line that got imported twice. Never reconcile against an
        # item that no longer has anything open.
        stale = target_lines.filtered(
            lambda l: l.reconciled or l.company_currency_id.is_zero(l.amount_residual)
        )
        if stale:
            raise UserError(_(
                "%s is already settled. Search again to get current suggestions.",
                ", ".join(stale.mapped("move_id.name")),
            ))

        undated = target_lines.filtered(lambda l: not (l.date_maturity or l.date))
        if undated:
            raise UserError(_(
                "%s has no date and cannot be reconciled. Such rows usually come "
                "from a migration; the date has to be corrected on the document "
                "first.",
                ", ".join(undated.mapped("move_id.name")),
            ))

        accounts = target_lines.account_id
        if len(accounts) != 1:
            raise UserError(_(
                "The selected documents use different accounts (%s). Assign them "
                "one at a time.",
                ", ".join(accounts.mapped("code")),
            ))
        partners = target_lines.partner_id
        if len(partners) > 1:
            raise UserError(_(
                "The selected documents belong to different partners. Assign them "
                "one at a time."
            ))

        suspense = self._matcher_counterpart_lines()
        if len(suspense) != 1:
            raise UserError(_(
                "Statement line %s has no single open counterpart line; it was "
                "probably already partly assigned.", self.display_name))

        move = self.move_id
        was_posted = move.state == "posted"
        if was_posted:
            move.button_draft()
        # date_maturity matters: Odoo sorts the items of a reconciliation by
        # "date_maturity or date". A receivable/payable line that carries
        # neither makes that expression return False, and sorting False against
        # a date raises a TypeError deep inside the reconciliation engine.
        suspense.write({
            "account_id": accounts.id,
            "partner_id": partners.id if partners else False,
            "date_maturity": suspense.date_maturity or self.date or move.date,
        })
        if was_posted:
            move.action_post()

        # Re-read: once the counterpart no longer sits on the suspense account,
        # _seek_for_lines reports it as an "other" line, so both buckets have to
        # be taken. Reconciling against the suspense bucket alone is a silent
        # no-op -- the statement line then looks assigned while the invoice
        # stays open.
        liquidity, suspense, other = self._seek_for_lines()
        counterpart = (suspense | other) - liquidity
        if not counterpart:
            raise UserError(_(
                "The counterpart line of %s disappeared while assigning it.",
                self.display_name))
        (counterpart + target_lines).reconcile()
        self.matcher_candidate_ids.unlink()
        self.matcher_state = "done"
        _logger.info(
            "Statement line %s assigned to %s",
            self.id, ", ".join(target_lines.mapped("move_id.name")),
        )
        return True

    def action_matcher_apply_best(self):
        """Apply the single best suggestion, refusing anything ambiguous.

        Two guards, both deliberate: a tie is never resolved by picking one, and
        a suggestion below the journal's confidence threshold is left alone. A
        match on the amount alone is right surprisingly often and wrong
        expensively, so by default it is shown but not booked.
        """
        applied = 0
        for line in self:
            if line.is_reconciled:
                continue
            candidates = line.matcher_candidate_ids
            if not candidates:
                continue
            best = max(candidates.mapped("score"))
            minimum = int(line.journal_id.matcher_auto_apply_min_score or "80")
            if best < minimum:
                _logger.info(
                    "Statement line %s skipped: best suggestion scores %s, "
                    "journal requires %s", line.id, best, minimum)
                continue
            top = candidates.filtered(lambda c: c.score == best)
            if len(top) != 1:
                _logger.info(
                    "Statement line %s skipped: %s equally scored suggestions",
                    line.id, len(top))
                continue
            line._matcher_apply(top.move_line_id)
            applied += 1
        return applied

    def action_matcher_unassign(self):
        """Undo an assignment made earlier, putting the amount back on hold."""
        for line in self:
            _liquidity, suspense, other = line._seek_for_lines()
            (suspense + other).remove_move_reconcile()
            suspense_account = line.journal_id.suspense_account_id \
                or line.company_id.account_journal_suspense_account_id
            move = line.move_id
            was_posted = move.state == "posted"
            if was_posted:
                move.button_draft()
            (suspense + other).write({"account_id": suspense_account.id})
            if was_posted:
                move.action_post()
            line.matcher_state = "todo"
        return True

    # ------------------------------------------------------------------
    # Hook into the import
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        auto = lines.filtered(lambda l: l.journal_id.matcher_auto_suggest)
        if auto:
            # Suggestions must never make an import fail.
            try:
                auto.action_matcher_refresh()
            except Exception:  # noqa: BLE001
                _logger.exception("Match suggestion failed for %s", auto.ids)
        return lines
