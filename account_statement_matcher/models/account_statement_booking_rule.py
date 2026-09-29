# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
"""Booking rules for bank lines that no open item can settle.

Rent, fees, interest and salaries are paid without any invoice, so the search
for open items rightly finds nothing.  Left alone, such a line stays on the
suspense account until somebody books it by hand -- or, worse, gets parked on
whatever vendor account happens to be at hand, which falsifies that vendor's
balance.

A rule says: *if the text of a bank line contains one of these words (and the
money moves in this direction, and optionally the partner is this one), book it
on this account*.  The module ships no rules because accounts differ per chart
of accounts and per company; they are plain configuration.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Shorter keywords match far too much ("kto", "bar", "ag").
MIN_KEYWORD_LENGTH = 3
# Booking on these would need a reconciliation, not a plain account.
FORBIDDEN_ACCOUNT_TYPES = (
    "asset_receivable", "liability_payable", "asset_cash", "liability_credit_card",
)


class AccountStatementBookingRule(models.Model):
    _name = "account.statement.booking.rule"
    _description = "Bank Line Booking Rule"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    direction = fields.Selection(
        selection=[
            ("out", "Money going out"),
            ("in", "Money coming in"),
            ("both", "Both"),
        ],
        required=True,
        default="out",
        help="Rent is paid, interest on a loan is paid, interest on a deposit "
             "is received: the same word can mean two different accounts.",
    )
    keywords = fields.Text(
        help="One word or phrase per line. The rule applies when the bank text, "
             "the reference or the name of the counterparty contains one of "
             "them. Capitalisation, spaces and punctuation do not matter.",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Only for partner",
        help="Restrict the rule to lines of this partner. Without keywords, "
             "every line of the partner in the chosen direction matches.",
    )
    account_id = fields.Many2one(
        comodel_name="account.account",
        string="Book on account",
        required=True,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable',"
               " 'asset_cash', 'liability_credit_card'))]",
    )
    assign_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Set partner to",
        help="Replace the partner of the line when booking. Useful when the "
             "bank text names a person but the import assigned the company "
             "itself.",
    )
    auto_apply = fields.Boolean(
        string="Book without asking",
        help="The bulk action books lines matched by this rule on its own. "
             "Without it the rule only proposes, and the line is booked from "
             "its form.",
    )

    @api.constrains("keywords", "partner_id")
    def _check_condition(self):
        for rule in self:
            if not rule._keyword_needles() and not rule.partner_id:
                raise ValidationError(_(
                    "Rule %s needs at least one keyword of %s characters or a partner.",
                    rule.name, MIN_KEYWORD_LENGTH,
                ))

    @api.constrains("account_id")
    def _check_account(self):
        for rule in self:
            if rule.account_id.account_type in FORBIDDEN_ACCOUNT_TYPES:
                raise ValidationError(_(
                    "Rule %(rule)s: %(account)s is a receivable, payable, bank or "
                    "credit card account. A rule books on a plain account; "
                    "open items are settled by the search.",
                    rule=rule.name, account=rule.account_id.display_name,
                ))

    def _keyword_needles(self):
        self.ensure_one()
        normalise = self.env["account.bank.statement.line"]._matcher_normalise
        needles = [normalise(word) for word in (self.keywords or "").splitlines()]
        return [n for n in needles if len(n) >= MIN_KEYWORD_LENGTH]

    def _matches(self, line, haystack):
        """True when this rule applies to the statement line."""
        self.ensure_one()
        if self.direction == "out" and line.amount >= 0:
            return False
        if self.direction == "in" and line.amount <= 0:
            return False
        if self.partner_id and (
            line.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id
        ):
            return False
        needles = self._keyword_needles()
        if (self.keywords or "").strip():
            # Keywords were given: at least one has to hit. A keyword that is
            # too short to be safe is dropped, and a rule left with none never
            # matches instead of matching everything.
            return any(needle in haystack for needle in needles)
        return bool(self.partner_id)
