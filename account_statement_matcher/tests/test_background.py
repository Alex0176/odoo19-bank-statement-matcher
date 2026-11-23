# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
from odoo import Command
from odoo.tests.common import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestBackgroundSearch(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.journal = cls.env["account.journal"].create({"name": "Bank T", "type": "bank", "code": "BKT"})
        cls.journal.matcher_auto_suggest = True
        cls.cron = cls.env.ref("account_statement_matcher.ir_cron_refresh_open")

    def bank_line(self, amount, ref="Zahlung"):
        return self.env["account.bank.statement.line"].create({
            "journal_id": self.journal.id, "date": "2026-10-10", "payment_ref": ref, "amount": amount,
            "partner_id": self.partner_a.id})

    def bill(self, amount=250.0, post=True):
        move = self.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": self.partner_a.id, "invoice_date": "2026-10-01",
            "invoice_line_ids": [Command.create({"name": "x", "quantity": 1, "price_unit": amount, "tax_ids": []})]})
        if post:
            move.action_post()
        return move

    def test_posting_schedules_one_background_run(self):
        self.env["ir.cron.trigger"].search([("cron_id", "=", self.cron.id)]).unlink()
        self.bill(100.0)
        self.bill(110.0)
        self.assertEqual(self.env["ir.cron.trigger"].search_count([("cron_id", "=", self.cron.id)]), 1,
                         "a burst of documents starts a single run")

    def test_late_document_is_found_and_assignable_from_the_document(self):
        line = self.bank_line(250.0)
        line.action_matcher_refresh()
        self.assertEqual(line.matcher_state, "none")
        move = self.bill(250.0)
        self.assertEqual(move.matcher_candidate_count, 0, "nothing searched yet")
        self.env["account.bank.statement.line"]._matcher_refresh_open()
        self.assertEqual(line.matcher_state, "suggested")
        move.invalidate_recordset()
        self.assertEqual(move.matcher_candidate_count, 1)
        action = move.action_matcher_assign()
        candidates = self.env["account.statement.match.candidate"].search(action["domain"])
        self.assertEqual(candidates.statement_line_id, line)
        candidates.action_apply()
        self.assertTrue(line.is_reconciled)
        move.invalidate_recordset()
        self.assertEqual(move.payment_state in ("paid", "in_payment"), True)
        self.assertEqual(move.matcher_candidate_count, 0)

    def test_refresh_all_button(self):
        a, b = self.bank_line(250.0), self.bank_line(80.0)
        self.bill(250.0)
        # a list header button passes the selected ids as an argument (call_button)
        result = self.env["account.bank.statement.line"].action_matcher_refresh_all([a.id])
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(a.matcher_state, "suggested")
        self.assertEqual(max(a.matcher_candidate_ids.mapped("score")), 80, "partner and amount")
        self.assertEqual(max(b.matcher_candidate_ids.mapped("score")), 30, "partner only")

    def test_invoice_opens_for_users_without_accounting_rights(self):
        """The suggestion count is computed for every user who opens an invoice, also without the accounting group."""
        move = self.bill(250.0)
        self.env["account.bank.statement.line"]._matcher_refresh_open()
        user = self.env["res.users"].create({
            "name": "Billing only", "login": "billing_only_t", "email": "b@example.com",
            "group_ids": [Command.set([self.env.ref("base.group_user").id, self.env.ref("account.group_account_invoice").id])],
        })
        count = move.with_user(user).read(["matcher_candidate_count"])[0]["matcher_candidate_count"]
        self.assertIsInstance(count, int)
