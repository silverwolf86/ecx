# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Cash Flow Statement handler tests.

Covers all three activity sections, multi counterpart moves, sign flow
(inflows positive, outflows negative), opening/closing cash balances,
the Balance Check identity, exclusion of pure cash transfers, posted only,
cancelled exclusion, error handling, orchestrator wiring, XLSX export.
"""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_dynamic_reports', 'integration', 'post_install', '-at_install')
class TestCashFlowHandler(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler = cls.env[
            'eh.account.dynamic.report.handler.cash_flow'
        ]
        cls.report = cls.env['eh.account.dynamic.report'].search(
            [('code', '=', 'cash_flow')], limit=1,
        )
        if not cls.report:
            cls.report = cls.env['eh.account.dynamic.report'].create({
                'code': 'cash_flow',
                'name': 'Cash Flow Statement',
                'handler_model':
                    'eh.account.dynamic.report.handler.cash_flow',
            })
        # Additional fixtures used only by Cash Flow tests.
        cls.account_fixed_asset = cls._ensure_account(
            cls.env, '1500', 'Equipment', 'asset_fixed',
        )
        cls.account_long_term_loan = cls._ensure_account(
            cls.env, '2500', 'Long Term Loan', 'liability_non_current',
        )

    def setUp(self):
        super().setUp()
        self.options = {
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'},
            'company_ids': [self.company.id],
            'posted_only': True,
            'show_zero': False,
        }

    def _post_in_period(self, lines, date_str='2026-06-15'):
        return self.post_balanced_move(
            lines, date=fields.Date.from_string(date_str),
        )

    @staticmethod
    def _line_by_id(result, line_id):
        for line in result['lines']:
            if line['id'] == line_id:
                return line
        return None

    @staticmethod
    def _amount(line):
        if line is None:
            return None
        for col in line['columns']:
            if col['expression_label'] == 'amount':
                return col['value']
        return None

    # ---- core classification ----

    def test_customer_payment_lands_in_operating_inflow(self):
        # First, create the receivable on a separate move.
        self._post_in_period([
            {'account': self.account_receivable, 'debit': 1000.0,
             'partner': self.partner_a},
            {'account': self.account_revenue, 'credit': 1000.0},
        ], date_str='2026-06-01')
        # Customer pays.
        self._post_in_period([
            {'account': self.account_cash, 'debit': 1000.0,
             'partner': self.partner_a},
            {'account': self.account_receivable, 'credit': 1000.0,
             'partner': self.partner_a},
        ], date_str='2026-06-15')

        result = self.handler.compute(self.options)
        # Operating section has a Receivables line worth +1000 (cash inflow
        # from customer collections).
        receivables_line = self._line_by_id(
            result, 'section-operating-line-asset_receivable',
        )
        self.assertIsNotNone(receivables_line)
        self.assertAlmostEqual(self._amount(receivables_line), 1000.0, places=2)
        self.assertAlmostEqual(
            result['totals']['operating'], 1000.0, places=2,
        )

    def test_direct_revenue_lands_in_operating(self):
        # Cash sale, no receivable.
        self._post_in_period([
            {'account': self.account_cash, 'debit': 500.0},
            {'account': self.account_revenue, 'credit': 500.0},
        ])
        result = self.handler.compute(self.options)
        income_line = self._line_by_id(
            result, 'section-operating-line-income',
        )
        self.assertIsNotNone(income_line)
        self.assertAlmostEqual(self._amount(income_line), 500.0, places=2)

    def test_equipment_purchase_lands_in_investing_outflow(self):
        self._post_in_period([
            {'account': self.account_fixed_asset, 'debit': 5000.0},
            {'account': self.account_cash, 'credit': 5000.0},
        ])
        result = self.handler.compute(self.options)
        fixed_line = self._line_by_id(
            result, 'section-investing-line-asset_fixed',
        )
        self.assertIsNotNone(fixed_line)
        # Cash outflow for fixed asset purchase: -5000.
        self.assertAlmostEqual(self._amount(fixed_line), -5000.0, places=2)
        self.assertAlmostEqual(
            result['totals']['investing'], -5000.0, places=2,
        )

    def test_loan_received_lands_in_financing_inflow(self):
        self._post_in_period([
            {'account': self.account_cash, 'debit': 10000.0},
            {'account': self.account_long_term_loan, 'credit': 10000.0},
        ])
        result = self.handler.compute(self.options)
        loan_line = self._line_by_id(
            result, 'section-financing-line-liability_non_current',
        )
        self.assertIsNotNone(loan_line)
        self.assertAlmostEqual(self._amount(loan_line), 10000.0, places=2)
        self.assertAlmostEqual(
            result['totals']['financing'], 10000.0, places=2,
        )

    def test_equity_injection_lands_in_financing(self):
        self._post_in_period([
            {'account': self.account_cash, 'debit': 20000.0},
            {'account': self.account_equity, 'credit': 20000.0},
        ])
        result = self.handler.compute(self.options)
        equity_line = self._line_by_id(
            result, 'section-financing-line-equity',
        )
        self.assertIsNotNone(equity_line)
        self.assertAlmostEqual(self._amount(equity_line), 20000.0, places=2)

    def test_multi_counterpart_move_splits_correctly(self):
        # DR Cash 1000 / CR Revenue 700 / CR Liability Current 300 (e.g. tax).
        liability_current = self._ensure_account(
            self.env, '2200', 'Tax Payable', 'liability_current',
        )
        self._post_in_period([
            {'account': self.account_cash, 'debit': 1000.0},
            {'account': self.account_revenue, 'credit': 700.0},
            {'account': liability_current, 'credit': 300.0},
        ])
        result = self.handler.compute(self.options)
        income_line = self._line_by_id(
            result, 'section-operating-line-income',
        )
        liab_line = self._line_by_id(
            result, 'section-operating-line-liability_current',
        )
        self.assertAlmostEqual(self._amount(income_line), 700.0, places=2)
        self.assertAlmostEqual(self._amount(liab_line), 300.0, places=2)
        self.assertAlmostEqual(
            result['totals']['operating'], 1000.0, places=2,
        )

    # ---- balance check identity ----

    def test_balance_check_zero_for_simple_inflow(self):
        self._post_in_period([
            {'account': self.account_cash, 'debit': 1000.0},
            {'account': self.account_revenue, 'credit': 1000.0},
        ])
        result = self.handler.compute(self.options)
        self.assertAlmostEqual(
            result['totals']['balance_check'], 0.0, places=2,
        )

    def test_balance_check_zero_for_complex_ledger(self):
        # Equity injection.
        self._post_in_period([
            {'account': self.account_cash, 'debit': 5000.0},
            {'account': self.account_equity, 'credit': 5000.0},
        ])
        # Direct revenue.
        self._post_in_period([
            {'account': self.account_cash, 'debit': 2000.0},
            {'account': self.account_revenue, 'credit': 2000.0},
        ])
        # Equipment purchase.
        self._post_in_period([
            {'account': self.account_fixed_asset, 'debit': 3000.0},
            {'account': self.account_cash, 'credit': 3000.0},
        ])
        # Vendor payment without prior payable (treat as expense direct).
        self._post_in_period([
            {'account': self.account_expense, 'debit': 500.0},
            {'account': self.account_cash, 'credit': 500.0},
        ])
        result = self.handler.compute(self.options)
        self.assertAlmostEqual(
            result['totals']['balance_check'], 0.0, places=2,
        )
        # Net change = 5000 + 2000 - 3000 - 500 = 3500.
        self.assertAlmostEqual(
            result['totals']['net_change_in_cash'], 3500.0, places=2,
        )
        self.assertAlmostEqual(
            result['totals']['closing_cash_balance']
            - result['totals']['opening_cash_balance'],
            3500.0, places=2,
        )

    def test_pure_cash_transfer_excluded(self):
        # Two cash accounts, transfer between them.
        bank = self._ensure_account(
            self.env, '1010', 'Bank Account', 'asset_cash',
        )
        self._post_in_period([
            {'account': bank, 'debit': 500.0},
            {'account': self.account_cash, 'credit': 500.0},
        ])
        result = self.handler.compute(self.options)
        # No section should record the transfer.
        self.assertAlmostEqual(
            result['totals']['operating'], 0.0, places=2,
        )
        self.assertAlmostEqual(
            result['totals']['investing'], 0.0, places=2,
        )
        self.assertAlmostEqual(
            result['totals']['financing'], 0.0, places=2,
        )
        self.assertAlmostEqual(
            result['totals']['net_change_in_cash'], 0.0, places=2,
        )

    # ---- date filtering ----

    def test_out_of_period_entries_excluded_from_net_change(self):
        # Pre period equity injection contributes to opening, not net change.
        self.post_balanced_move(
            [
                {'account': self.account_cash, 'debit': 1000.0},
                {'account': self.account_equity, 'credit': 1000.0},
            ],
            date=fields.Date.from_string('2025-12-15'),
        )
        # In period revenue.
        self._post_in_period([
            {'account': self.account_cash, 'debit': 200.0},
            {'account': self.account_revenue, 'credit': 200.0},
        ])
        result = self.handler.compute(self.options)
        # Opening = 1000, net change = 200, closing = 1200.
        self.assertAlmostEqual(
            result['totals']['opening_cash_balance'], 1000.0, places=2,
        )
        self.assertAlmostEqual(
            result['totals']['net_change_in_cash'], 200.0, places=2,
        )
        self.assertAlmostEqual(
            result['totals']['closing_cash_balance'], 1200.0, places=2,
        )

    # ---- state filtering ----

    def test_posted_only_excludes_draft(self):
        self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': '2026-06-15',
            'line_ids': [
                (0, 0, {'account_id': self.account_cash.id, 'debit': 999.0}),
                (0, 0, {'account_id': self.account_revenue.id, 'credit': 999.0}),
            ],
        })
        result = self.handler.compute(self.options)
        self.assertAlmostEqual(
            result['totals']['net_change_in_cash'], 0.0, places=2,
        )

    def test_cancelled_excluded(self):
        move = self._post_in_period([
            {'account': self.account_cash, 'debit': 444.0},
            {'account': self.account_revenue, 'credit': 444.0},
        ])
        move.button_cancel()
        result = self.handler.compute(self.options)
        self.assertAlmostEqual(
            result['totals']['net_change_in_cash'], 0.0, places=2,
        )

    # ---- structural ----

    def test_three_section_headers_present(self):
        self._post_in_period([
            {'account': self.account_cash, 'debit': 100.0},
            {'account': self.account_revenue, 'credit': 100.0},
        ])
        result = self.handler.compute(self.options)
        kinds = [
            (l.get('meta') or {}).get('kind')
            for l in result['lines']
        ]
        self.assertEqual(kinds.count('section_header'), 3)
        self.assertEqual(kinds.count('section_total'), 3)
        # Net Change, Opening, Closing, Balance Check.
        self.assertIn('net_change', kinds)
        self.assertIn('cash_balance', kinds)
        self.assertIn('balance_check', kinds)

    def test_zero_section_lines_hidden_by_default(self):
        # Only operating activity; investing/financing line bodies should be
        # hidden (only their headers and totals show).
        self._post_in_period([
            {'account': self.account_cash, 'debit': 100.0},
            {'account': self.account_revenue, 'credit': 100.0},
        ])
        result = self.handler.compute(self.options)
        section_lines = [
            l for l in result['lines']
            if (l.get('meta') or {}).get('kind') == 'section_line'
        ]
        # Only the income line should appear.
        self.assertEqual(len(section_lines), 1)
        self.assertEqual(
            section_lines[0]['meta']['account_type'], 'income',
        )

    # ---- error handling ----

    def test_missing_dates_raise(self):
        bad = dict(self.options)
        bad.pop('date')
        with self.assertRaises(UserError):
            self.handler.compute(bad)

    # ---- orchestrator wiring ----

    def test_orchestrator_renders(self):
        self._post_in_period([
            {'account': self.account_cash, 'debit': 100.0},
            {'account': self.account_revenue, 'credit': 100.0},
        ])
        result = self.report.render(self.options)
        self.assertFalse(result['from_cache'])

    def test_orchestrator_cache_hit_on_second_render(self):
        self._post_in_period([
            {'account': self.account_cash, 'debit': 100.0},
            {'account': self.account_revenue, 'credit': 100.0},
        ])
        first = self.report.render(self.options)
        second = self.report.render(self.options)
        self.assertFalse(first['from_cache'])
        self.assertTrue(second['from_cache'])
        self.assertEqual(first['totals'], second['totals'])

    # ---- XLSX export ----

    def test_xlsx_export_renders_workbook(self):
        self._post_in_period([
            {'account': self.account_cash, 'debit': 100.0},
            {'account': self.account_revenue, 'credit': 100.0},
        ])
        content = self.report.render_xlsx(self.options)
        self.assertEqual(content[:2], b'PK')
        self.assertGreater(len(content), 1000)
