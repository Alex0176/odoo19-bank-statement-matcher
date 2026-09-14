# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
"""Send the user to the assignment screen right after an import.

The OCA import wizard ends on the list of imported statements, which is a dead
end: the next thing anybody wants is to assign the new lines to documents. This
bridge replaces that final action.

It lives in its own module on purpose. The matcher itself depends on ``account``
alone so that it installs anywhere; knowing about the OCA importer is an extra
that only makes sense when that importer is present -- hence ``auto_install``.
"""

from odoo import _, models


class AccountStatementImport(models.TransientModel):
    _inherit = "account.statement.import"

    def import_file_button(self):
        action = super().import_file_button()

        # A notification action means the import had something to report; the
        # user should read that first, so the redirect is skipped.
        if not isinstance(action, dict) or action.get("type") != "ir.actions.act_window":
            return action

        statement_ids = []
        for leaf in action.get("domain") or []:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "id":
                statement_ids = leaf[2]
        if not statement_ids:
            return action

        lines = self.env["account.bank.statement.line"].search(
            [("statement_id", "in", statement_ids)])
        if not lines:
            return action

        assignment = self.env["ir.actions.actions"]._for_xml_id(
            "account_statement_matcher.action_statement_line_matcher")
        assignment["domain"] = [("id", "in", lines.ids)]
        assignment["context"] = {"search_default_unassigned": 1}
        assignment["name"] = _("Assign Bank Lines")
        return assignment
