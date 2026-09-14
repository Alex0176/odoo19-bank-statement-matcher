# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
"""Per-journal switch for automatic suggestions."""

from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    matcher_auto_suggest = fields.Boolean(
        string="Suggest matches on import",
        default=True,
        help="Search for matching invoices, bills, credit notes and payments "
             "as soon as a statement line is created. Suggestions are only "
             "proposed; nothing is booked without a user confirming it.",
    )
    matcher_auto_apply_min_score = fields.Selection(
        selection=[
            ("100", "Only when a document reference was found"),
            ("80", "Reference, or partner and amount together"),
            ("60", "Also when the amount alone is unique"),
        ],
        string="Assign automatically from",
        default="80",
        required=True,
        help="Confidence a suggestion needs before the bulk action assigns it "
             "without being asked. Weaker suggestions are still shown, they "
             "just have to be confirmed one by one.",
    )
