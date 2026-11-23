# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
from odoo.exceptions import UserError
from odoo.tests.common import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPrivatePayments(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.env["account.journal"].create({"name": "Card", "type": "bank", "code": "CRD"})
        cls.private_account = cls.env["account.account"].create({
            "name": "Claim owner", "code": "299999", "account_type": "asset_current"})

    def line(self, amount=-100.0, ref="Hotel"):
        return self.env["account.bank.statement.line"].create({
            "journal_id": self.journal.id, "date": "2026-10-10", "payment_ref": ref, "amount": amount})

    def test_marking_does_not_book_anything(self):
        line = self.line()
        line.action_matcher_mark_private()
        self.assertTrue(line.matcher_private)
        self.assertTrue(line.matcher_private_open)
        self.assertFalse(line.is_reconciled)

    def test_book_private_needs_the_account_and_moves_the_suspense_line(self):
        line = self.line()
        with self.assertRaises(UserError):
            line.action_matcher_book_private()
        self.journal.matcher_private_account_id = self.private_account
        line.action_matcher_book_private()
        self.assertTrue(line.is_reconciled)
        self.assertEqual(line.matcher_state, "done")
        self.assertIn(self.private_account, line.move_id.line_ids.account_id)

    def test_settling_sums_the_amounts_and_locks_the_mark(self):
        a, b = self.line(-100.0), self.line(-23.5, "Taxi")
        (a + b).action_matcher_mark_private()
        wizard = self.env["account.statement.private.settle.wizard"].with_context(
            active_model="account.bank.statement.line", active_ids=(a + b).ids).create({"reference": "T1"})
        self.assertEqual(wizard.count, 2)
        self.assertAlmostEqual(wizard.total, 123.5)
        wizard.action_settle()
        self.assertFalse(a.matcher_private_open)
        self.assertEqual(a.matcher_private_settled_ref, "T1")
        with self.assertRaises(UserError):
            a.action_matcher_unmark_private()
