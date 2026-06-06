# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Shared test fixtures for the ERP Heritage accounting suite.

Two base classes:

* EhAccountUnitTestCase: pure unit tests, no DB seeding beyond what TransactionCase
  already provides. Use for SQL builder shape assertions, cache layer tests,
  options canonicalisation tests.
* EhAccountIntegrationTestCase: integration tests that need a chart of accounts
  and a posted journal entry. The setUpClass seeds a minimal CoA and a
  reusable balanced entry.
"""

from odoo import fields
from odoo.tests import TransactionCase


class EhAccountUnitTestCase(TransactionCase):
    """Lightweight base class. No accounting fixtures.

    Suitable for tests that exercise pure Python helpers (SQL builder, cache,
    canonicalisation) and only need self.env.cr to be available.
    """


class EhAccountIntegrationTestCase(TransactionCase):
    """Integration base class with a seeded chart of accounts and partners."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.account_receivable = cls._ensure_account(
            cls.env, '1100', 'Trade Receivables', 'asset_receivable',
        )
        cls.account_payable = cls._ensure_account(
            cls.env, '2100', 'Trade Payables', 'liability_payable',
        )
        cls.account_revenue = cls._ensure_account(
            cls.env, '4000', 'Sales Revenue', 'income',
        )
        cls.account_expense = cls._ensure_account(
            cls.env, '5000', 'Cost of Sales', 'expense',
        )
        cls.account_cash = cls._ensure_account(
            cls.env, '1000', 'Cash on Hand', 'asset_cash',
        )
        cls.account_equity = cls._ensure_account(
            cls.env, '3000', 'Owner Equity', 'equity',
        )

        cls.journal_misc = cls.env['account.journal'].search(
            [('company_id', '=', cls.company.id), ('type', '=', 'general')],
            limit=1,
        )
        if not cls.journal_misc:
            cls.journal_misc = cls.env['account.journal'].create({
                'name': 'Miscellaneous',
                'code': 'MISC',
                'type': 'general',
                'company_id': cls.company.id,
            })

        cls.partner_a = cls.env['res.partner'].create({'name': 'Test Partner A'})
        cls.partner_b = cls.env['res.partner'].create({'name': 'Test Partner B'})

    @staticmethod
    def _ensure_account(env, code, name, account_type):
        existing = env['account.account'].search(
            [
                ('code', '=', code),
                ('company_ids', 'in', env.company.ids),
            ],
            limit=1,
        )
        if existing:
            return existing
        vals = {
            'code': code,
            'name': name,
            'account_type': account_type,
            'company_ids': [(6, 0, env.company.ids)],
        }
        # Reconcilable types must carry reconcile=True for amount_residual to
        # compute correctly. Aged receivable/payable tests rely on this.
        if account_type in (
            'asset_receivable', 'liability_payable', 'liability_credit_card',
        ):
            vals['reconcile'] = True
        return env['account.account'].create(vals)

    @classmethod
    def post_balanced_move(cls, lines, journal=None, date=None):
        """Helper: create and post a balanced journal entry.

        :param lines: list of dicts with keys: account (required), debit,
            credit, partner, name, date_maturity.
        :param journal: optional account.journal record (defaults to misc).
        :param date: optional date (defaults to today).
        :return: the posted account.move record.
        """
        journal = journal or cls.journal_misc
        date = date or fields.Date.today()
        line_vals = []
        for line in lines:
            vals = {
                'account_id': line['account'].id,
                'debit': line.get('debit', 0.0),
                'credit': line.get('credit', 0.0),
                'partner_id': line['partner'].id if line.get('partner') else False,
                'name': line.get('name', '/'),
            }
            if 'date_maturity' in line:
                vals['date_maturity'] = line['date_maturity']
            line_vals.append((0, 0, vals))
        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': date,
            'line_ids': line_vals,
        })
        move.action_post()
        return move
