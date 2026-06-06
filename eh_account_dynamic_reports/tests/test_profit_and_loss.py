# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Profit and Loss handler tests.

Covers:

* Income only entries: net profit equals income amount.
* Expense only entries: net profit equals minus expense amount.
* Mixed: net profit equals income minus expenses.
* Section structure: header, account lines, section total per section.
* Net Profit row sits at the bottom.
* Zero balance accounts hidden by default.
* posted_only excludes draft entries; setting it false includes them.
* Cancelled entries excluded.
* Out of period entries not included.
* Account, journal, partner filters narrow the result set.
* Missing date raises a UserError.
* Orchestrator render works and respects the cache.
* Drill down works for account lines, returns None for section markers.
"""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_dynamic_reports', 'integration', 'post_install', '-at_install')
class TestProfitAndLossHandler(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler = cls.env[
            'eh.account.dynamic.report.handler.profit_and_loss'
        ]
        cls.report = cls.env['eh.account.dynamic.report'].search(
            [('code', '=', 'profit_and_loss')], limit=1,
        )
        if not cls.report:
            cls.report = cls.env['eh.account.dynamic.report'].create({
                'code': 'profit_and_loss',
                'name': 'Profit and Loss',
                'handler_model':
                    'eh.account.dynamic.report.handler.profit_and_loss',
            })

    def setUp(self):
        super().setUp()
        self.options = {
            'date': {'date_from': '2026-01-01', 'date_to': '2026-12-31'},
            'company_ids': [self.company.id],
            'posted_only': True,
            'show_zero': False,
        }

    def _post_in_period(self, lines):
        return self.post_balanced_move(
            lines, date=fields.Date.from_string('2026-06-15'),
        )

    @staticmethod
    def _line_by_id(result, line_id):
        for line in result['lines']:
            if line['id'] == line_id:
                return line
        return None

    @staticmethod
    def _line_by_meta_kind(result, kind):
        return [
            line for line in result['lines']
            if (line.get('meta') or {}).get('kind') == kind
        ]

    @staticmethod
    def _amount(line):
        for col in line['columns']:
            if col['expression_label'] == 'amount':
                return col['value']
        return None

    # ---- core math ----

    def test_income_only_yields_positive_net_profit(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 1000.0},
            {'account': self.account_cash, 'debit': 1000.0},
        ])
        result = self.handler.compute(self.options)
        net = self._line_by_id(result, 'net_profit')
        self.assertIsNotNone(net)
        self.assertAlmostEqual(self._amount(net), 1000.0, places=2)
        self.assertAlmostEqual(result['totals']['net_profit'], 1000.0, places=2)

    def test_expense_only_yields_negative_net_profit(self):
        self._post_in_period([
            {'account': self.account_expense, 'debit': 300.0},
            {'account': self.account_cash, 'credit': 300.0},
        ])
        result = self.handler.compute(self.options)
        net = self._line_by_id(result, 'net_profit')
        self.assertAlmostEqual(self._amount(net), -300.0, places=2)

    def test_mixed_income_minus_expenses(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 1000.0},
            {'account': self.account_cash, 'debit': 1000.0},
        ])
        self._post_in_period([
            {'account': self.account_expense, 'debit': 300.0},
            {'account': self.account_cash, 'credit': 300.0},
        ])
        result = self.handler.compute(self.options)
        self.assertAlmostEqual(
            result['totals']['income'], 1000.0, places=2,
        )
        self.assertAlmostEqual(
            result['totals']['expenses'], 300.0, places=2,
        )
        self.assertAlmostEqual(
            result['totals']['net_profit'], 700.0, places=2,
        )

    def test_section_structure_present(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        result = self.handler.compute(self.options)
        headers = self._line_by_meta_kind(result, 'section_header')
        totals = self._line_by_meta_kind(result, 'section_total')
        self.assertEqual(len(headers), 2,
                         "Income and Expenses section headers must appear")
        self.assertEqual(len(totals), 2,
                         "Income and Expenses section totals must appear")
        self.assertEqual({h['name'] for h in headers},
                         {'Income', 'Expenses'})
        # Net Profit always at the bottom.
        self.assertEqual(result['lines'][-1]['id'], 'net_profit')

    def test_section_totals_match_account_sum(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 600.0},
            {'account': self.account_cash, 'debit': 600.0},
        ])
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 400.0},
            {'account': self.account_cash, 'debit': 400.0},
        ])
        result = self.handler.compute(self.options)
        income_total = next(
            self._amount(l) for l in result['lines']
            if l['id'] == 'section-income-total'
        )
        self.assertAlmostEqual(income_total, 1000.0, places=2)

    # ---- filter behaviour ----

    def test_zero_balance_account_hidden_by_default(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        result = self.handler.compute(self.options)
        # Expense account untouched: should not appear as a sub line.
        sub_account_lines = [
            l for l in result['lines']
            if (l.get('meta') or {}).get('account_code')
        ]
        codes = {l['meta']['account_code'] for l in sub_account_lines}
        self.assertNotIn('5000', codes)

    def test_account_filter(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        self._post_in_period([
            {'account': self.account_expense, 'debit': 50.0},
            {'account': self.account_cash, 'credit': 50.0},
        ])
        opts = dict(self.options)
        opts['account_ids'] = [self.account_revenue.id]
        result = self.handler.compute(opts)
        # Only revenue account contributes; net profit = income.
        self.assertAlmostEqual(
            result['totals']['net_profit'], 100.0, places=2,
        )

    def test_partner_filter(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0,
             'partner': self.partner_a},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 200.0,
             'partner': self.partner_b},
            {'account': self.account_cash, 'debit': 200.0},
        ])
        opts = dict(self.options)
        opts['partner_ids'] = [self.partner_a.id]
        result = self.handler.compute(opts)
        self.assertAlmostEqual(
            result['totals']['net_profit'], 100.0, places=2,
        )

    # ---- state filtering ----

    def test_posted_only_excludes_draft(self):
        self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': '2026-06-15',
            'line_ids': [
                (0, 0, {'account_id': self.account_revenue.id, 'credit': 999.0}),
                (0, 0, {'account_id': self.account_cash.id, 'debit': 999.0}),
            ],
        })
        result = self.handler.compute(self.options)
        self.assertAlmostEqual(
            result['totals']['net_profit'], 0.0, places=2,
        )

    def test_posted_only_false_includes_draft(self):
        self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_misc.id,
            'date': '2026-06-15',
            'line_ids': [
                (0, 0, {'account_id': self.account_revenue.id, 'credit': 333.0}),
                (0, 0, {'account_id': self.account_cash.id, 'debit': 333.0}),
            ],
        })
        opts = dict(self.options)
        opts['posted_only'] = False
        result = self.handler.compute(opts)
        self.assertAlmostEqual(
            result['totals']['net_profit'], 333.0, places=2,
        )

    def test_cancelled_excluded(self):
        move = self._post_in_period([
            {'account': self.account_revenue, 'credit': 444.0},
            {'account': self.account_cash, 'debit': 444.0},
        ])
        move.button_cancel()
        result = self.handler.compute(self.options)
        self.assertAlmostEqual(
            result['totals']['net_profit'], 0.0, places=2,
        )

    def test_out_of_period_excluded(self):
        # Entry before the period.
        self.post_balanced_move(
            [
                {'account': self.account_revenue, 'credit': 1000.0},
                {'account': self.account_cash, 'debit': 1000.0},
            ],
            date=fields.Date.from_string('2025-12-15'),
        )
        # Entry after the period.
        self.post_balanced_move(
            [
                {'account': self.account_revenue, 'credit': 2000.0},
                {'account': self.account_cash, 'debit': 2000.0},
            ],
            date=fields.Date.from_string('2027-01-15'),
        )
        result = self.handler.compute(self.options)
        self.assertAlmostEqual(
            result['totals']['net_profit'], 0.0, places=2,
        )

    # ---- error handling ----

    def test_missing_date_raises(self):
        bad = dict(self.options)
        bad.pop('date')
        with self.assertRaises(UserError):
            self.handler.compute(bad)

    def test_missing_date_from_raises(self):
        bad = dict(self.options)
        bad['date'] = {'date_to': '2026-12-31'}
        with self.assertRaises(UserError):
            self.handler.compute(bad)

    # ---- orchestrator wiring ----

    def test_orchestrator_renders(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        result = self.report.render(self.options)
        self.assertFalse(result['from_cache'])
        self.assertIn('execution_id', result)
        self.assertGreater(len(result['lines']), 0)

    def test_orchestrator_cache_hit_on_second_render(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        first = self.report.render(self.options)
        second = self.report.render(self.options)
        self.assertFalse(first['from_cache'])
        self.assertTrue(second['from_cache'])
        self.assertEqual(first['totals'], second['totals'])

    # ---- drill down ----

    def test_drilldown_action_for_account_line(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 75.0},
            {'account': self.account_cash, 'debit': 75.0},
        ])
        action = self.handler.get_drilldown_action(
            self.options, "account-%s" % self.account_revenue.id,
        )
        self.assertIsNotNone(action)
        self.assertEqual(action['res_model'], 'account.move.line')
        items = self.env['account.move.line'].search(action['domain'])
        self.assertIn(
            self.account_revenue.id, items.mapped('account_id.id'),
        )

    def test_drilldown_returns_none_for_section_marker(self):
        self.assertIsNone(self.handler.get_drilldown_action(
            self.options, 'section-income-header',
        ))
        self.assertIsNone(self.handler.get_drilldown_action(
            self.options, 'section-expenses-total',
        ))
        self.assertIsNone(self.handler.get_drilldown_action(
            self.options, 'net_profit',
        ))

    # ---- XLSX export ----

    def test_xlsx_export_renders_workbook(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        content = self.report.render_xlsx(self.options)
        self.assertEqual(content[:2], b'PK')
        self.assertGreater(len(content), 1000,
                           "XLSX should contain meaningful content")
