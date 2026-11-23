# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
"""One proposed assignment between a statement line and an open item.

Suggestions are stored instead of recomputed on the fly so that a user can look
at a statement days later and still see what was proposed -- and so that a line
which found nothing at import time can simply be searched again once the missing
document exists.
"""

from odoo import _, api, fields, models


class AccountStatementMatchCandidate(models.Model):
    _name = "account.statement.match.candidate"
    _description = "Bank Statement Match Suggestion"
    _order = "score desc, id"
    _rec_name = "display_name"

    statement_line_id = fields.Many2one(
        comodel_name="account.bank.statement.line",
        string="Statement Line",
        required=True,
        ondelete="cascade",
        index=True,
    )
    move_line_id = fields.Many2one(
        comodel_name="account.move.line",
        string="Open Item",
        required=True,
        ondelete="cascade",
    )
    move_id = fields.Many2one(
        related="move_line_id.move_id", string="Document", store=True,
    )
    partner_id = fields.Many2one(
        related="move_line_id.partner_id", string="Partner", store=True,
    )
    date = fields.Date(related="move_line_id.date", string="Document Date")
    amount_residual = fields.Monetary(
        related="move_line_id.amount_residual",
        string="Open Amount",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(related="move_line_id.company_currency_id")
    line_date = fields.Date(related="statement_line_id.date", string="Bank Date")
    line_text = fields.Char(related="statement_line_id.payment_ref", string="Bank Text")
    line_amount = fields.Monetary(related="statement_line_id.amount", string="Bank Amount",
                                  currency_field="line_currency_id")
    line_currency_id = fields.Many2one(related="statement_line_id.currency_id")
    score = fields.Integer(
        string="Confidence",
        help="100 a document reference was found in the bank text, "
             "80 partner and amount match, "
             "60 the amount identifies a single open item, "
             "30 partner only.",
    )
    rule = fields.Selection(
        selection=[
            ("reference", "Reference found"),
            ("partner_amount", "Partner and amount"),
            ("amount_unique", "Unique amount"),
            ("partner", "Partner only"),
        ],
        string="Matched by",
    )

    @api.depends("move_id", "amount_residual")
    def _compute_display_name(self):
        for candidate in self:
            candidate.display_name = "%s (%s)" % (
                candidate.move_id.name or "?", candidate.amount_residual,
            )

    def action_apply(self):
        """Assign the statement line to exactly this open item."""
        self.ensure_one()
        self.statement_line_id._matcher_apply(self.move_line_id)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_open_document(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "name": _("Document"),
        }
