# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
"""Sum up private payments and note that they were transferred back."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StatementPrivateSettleWizard(models.TransientModel):
    _name = "account.statement.private.settle.wizard"
    _description = "Private payments paid back"

    line_ids = fields.Many2many("account.bank.statement.line", "private_settle_wizard_line_rel", "wizard_id", "line_id", string="Private payments")
    date = fields.Date(string="Paid back on", default=fields.Date.context_today, required=True)
    reference = fields.Char(string="Reference of the transfer")
    total = fields.Monetary(string="Total to transfer", compute="_compute_total", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", compute="_compute_total")
    count = fields.Integer(compute="_compute_total")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "line_ids" in fields_list and not values.get("line_ids"):
            if self.env.context.get("active_model") == "account.bank.statement.line":
                lines = self.env["account.bank.statement.line"].browse(
                    self.env.context.get("active_ids") or []).filtered("matcher_private_open")
                values["line_ids"] = [(6, 0, lines.ids)]
        return values

    @api.depends("line_ids")
    def _compute_total(self):
        for wizard in self:
            lines = wizard.line_ids.filtered("matcher_private_open")
            wizard.count = len(lines)
            wizard.currency_id = lines[:1].company_id.currency_id or self.env.company.currency_id
            # a payment is negative on the card: the amount to transfer is positive
            wizard.total = -sum(lines.mapped("amount"))

    def action_settle(self):
        self.ensure_one()
        lines = self.line_ids.filtered("matcher_private_open")
        if not lines:
            raise UserError(_("No open private payment is selected."))
        lines.write({"matcher_private_settled_date": self.date, "matcher_private_settled_ref": self.reference or False})
        return {"type": "ir.actions.act_window_close"}
