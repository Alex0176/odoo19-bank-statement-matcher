# Copyright 2026 Biricon IT Services GmbH
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl-3.0).
{
    "name": "Bank Statement Matcher",
    "summary": "Suggest and apply the reconciliation of bank statement lines "
               "with invoices, bills, credit notes and payments",
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "author": "Biricon IT Services GmbH",
    "website": "https://github.com/Alex0176/odoo19-bank-statement-matcher",
    "license": "AGPL-3",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "views/account_bank_statement_line_views.xml",
        "views/account_journal_views.xml",
        "wizard/statement_match_wizard_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
