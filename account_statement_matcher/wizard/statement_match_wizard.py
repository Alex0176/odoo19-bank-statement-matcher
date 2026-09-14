# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
"""Review screen for a whole statement.

The per-line form is fine for a single correction, but after an import a user
wants one list: which lines have a confident suggestion, which are ambiguous,
which found nothing.  This wizard is that list, plus the two bulk actions
"search again" and "apply the unambiguous ones".
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StatementMatchWizard(models.TransientModel):
    _name = "account.statement.match.wizard"
    _description = "Assign Bank Statement Lines"

    line_ids = fields.Many2many(
        comodel_name="account.bank.statement.line",
        string="Statement Lines",
    )
    only_unassigned = fields.Boolean(
        string="Only unassigned lines", default=True,
    )
    message = fields.Char(string="Result", readonly=True)

    @api.model
    def default_get(self, fields_list):
        """Pick up the lines ticked in the list the wizard was started from."""
        values = super().default_get(fields_list)
        if "line_ids" in fields_list and not values.get("line_ids"):
            active_ids = self.env.context.get("active_ids") or []
            if self.env.context.get("active_model") == "account.bank.statement.line":
                values["line_ids"] = [(6, 0, active_ids)]
        return values

    def _target_lines(self):
        lines = self.line_ids
        if self.only_unassigned:
            lines = lines.filtered(lambda l: not l.is_reconciled)
        return lines

    def action_refresh(self):
        """Search again -- the point of the whole exercise for late documents."""
        lines = self._target_lines()
        lines.action_matcher_refresh()
        return self._reopen(
            _("%s line(s) searched again.", len(lines))
        )

    def action_apply(self):
        """Apply every unambiguous suggestion, skip everything else.

        Deliberately all-or-nothing per line, never per statement: one line that
        cannot be assigned must not stop the others, but a line that fails
        halfway would leave the books inconsistent, so ``_matcher_apply`` either
        completes or raises.
        """
        lines = self._target_lines()
        applied = skipped = failed = 0
        for line in lines:
            try:
                with self.env.cr.savepoint():
                    if line.action_matcher_apply_best():
                        applied += 1
                    else:
                        skipped += 1
            except UserError as err:
                # Rolling back the savepoint undoes the rows but not the ORM
                # cache, which still points at suggestion records that no longer
                # exist. Without this the next line fails with a misleading
                # "record does not exist" instead of its own real problem.
                self.env.invalidate_all()
                failed += 1
                _logger.warning("Statement line %s not assigned: %s", line.id, err)
        return self._reopen(_(
            "%(applied)s assigned, %(skipped)s left for review, %(failed)s failed.",
            applied=applied, skipped=skipped, failed=failed,
        ))

    def _reopen(self, message):
        """Show the result without leaving the review screen."""
        self.message = message
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
