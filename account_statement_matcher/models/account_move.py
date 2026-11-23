# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
"""Invoices and bills know their bank line suggestions, and start the search.

* A new posted invoice, bill or credit note may be the document an unassigned bank line
  has been waiting for, so posting one schedules a background search over all open bank
  lines (one run shortly after, however many documents are posted in a burst).
* When that search found a suggestion for a document, the document itself shows an
  "Assign" button, so the assignment can be made from either side.
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

TRIGGER_DELAY_SECONDS = 60


class AccountMove(models.Model):
    _inherit = "account.move"

    matcher_candidate_count = fields.Integer(
        string="Bank Line Suggestions", compute="_compute_matcher_candidate_count")

    @api.depends("state", "payment_state")
    def _compute_matcher_candidate_count(self):
        counts = {}
        ids = self.filtered(lambda m: m.id and m.is_invoice(include_receipts=True)).ids
        if ids:
            groups = self.env["account.statement.match.candidate"]._read_group(
                [("move_id", "in", ids), ("statement_line_id.is_reconciled", "=", False)],
                groupby=["move_id"], aggregates=["__count"])
            counts = {move.id: count for move, count in groups}
        for move in self:
            move.matcher_candidate_count = counts.get(move.id, 0)

    def action_matcher_assign(self):
        """Show the bank lines suggested for this document; assigning is one click per row."""
        self.ensure_one()
        candidates = self.env["account.statement.match.candidate"].search(
            [("move_id", "=", self.id), ("statement_line_id.is_reconciled", "=", False)])
        return {
            "type": "ir.actions.act_window",
            "name": _("Assign to a bank line"),
            "res_model": "account.statement.match.candidate",
            "view_mode": "list",
            "views": [(self.env.ref("account_statement_matcher.view_match_candidate_for_move").id, "list")],
            "domain": [("id", "in", candidates.ids)],
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Background trigger
    # ------------------------------------------------------------------
    def _matcher_schedule_search(self):
        """One background run shortly after documents were posted (never fails the posting)."""
        try:
            cron = self.env.ref("account_statement_matcher.ir_cron_refresh_open", raise_if_not_found=False)
            if not cron:
                return
            cron = cron.sudo()
            pending = self.env["ir.cron.trigger"].sudo().search_count([("cron_id", "=", cron.id)])
            if not pending:
                cron._trigger(at=fields.Datetime.now() + timedelta(seconds=TRIGGER_DELAY_SECONDS))
        except Exception:  # noqa: BLE001
            _logger.exception("Could not schedule the bank line search")

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        if posted.filtered(lambda m: m.is_invoice(include_receipts=True)):
            posted._matcher_schedule_search()
        return posted
