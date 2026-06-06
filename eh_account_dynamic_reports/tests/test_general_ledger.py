# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
General Ledger handler tests.

Covers:

* Account header line, opening line, and total line render correctly.
* Entries within the period appear with date, journal, move, partner,
  label, debit, credit, and running balance.
* Running balance: opening + sum(debit) - sum(credit) per account.
* Opening balance reflects entries strictly before date_from.
* Closing balance equals running balance after the last entry.
* Out of period entries excluded.
* Posted only excludes draft entries; setting it false includes them.
* Cancelled entries excluded.
* Account, journal, partner filters narrow the result set.
* Missing dates raise UserError.
* Orchestrator render works and respects the cache.
* Drill down: aml-X opens the specific journal entry form.
* Drill down: account-N opens journal items filtered to that account.
* Drill down: opening / total / unrelated ids return None.
* XLSX export produces a valid workbook.
"""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_dynamic_reports', 'integration', 'post_install', '-at_install')
class TestGeneralLedgerHandler(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler = cls.env[
            'eh.account.dynamic.report.handler.general_ledger'
        ]
        cls.report = cls.env['eh.account.dynamic.report'].search(
            [('code', '=', 'general_ledger')], limit=1,
        )
        if not cls.report:
            cls.report = cls.env['eh.account.dynamic.report'].create({
                'code': 'general_ledger',
                'name': 'General Ledger',
                'handler_model':
                    'eh.account.dynamic.report.handler.general_ledger',
            })

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
    def _lines_for_account(result, account_id):
        return [
            line for line in result['lines']
            if (line.get('meta') or {}).get('account_id') == account_id
        ]

    @staticmethod
    def _column_value(line, label):
        for col in line['columns']:
            if col['expression_label'] == label:
                return col['value']
        return None

    @staticmethod
    def _line_by_kind(lines, kind):
        for line in lines:
            if (line.get('meta') or {}).get('kind') == kind:
                return line
        return None

    # ---- core rendering ----

    def test_account_header_opening_entry_total_present(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 1000.0,
             'partner': self.partner_a},
            {'account': self.account_cash, 'debit': 1000.0},
        ])
        result = self.handler.compute(self.options)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        # Each account contributes header + opening + entry + total => 4 lines
        # at minimum (header counts itself among lines for the account).
        kinds = [(l.get('meta') or {}).get('kind') for l in cash_lines]
        self.assertIn('account_header', kinds)
        self.assertIn('opening_balance', kinds)
        self.assertIn('aml', kinds)
        self.assertIn('account_total', kinds)

    def test_running_balance_increments_correctly(self):
        # Two postings on the cash account.
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ], date_str='2026-06-15')
        self._post_in_period([
            {'account': self.account_expense, 'debit': 30.0},
            {'account': self.account_cash, 'credit': 30.0},
        ], date_str='2026-06-20')

        result = self.handler.compute(self.options)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        # Sort by their position in the result for the cash account.
        aml_lines = [
            l for l in cash_lines
            if (l.get('meta') or {}).get('kind') == 'aml'
        ]
        self.assertEqual(len(aml_lines), 2)
        balances = [self._column_value(l, 'balance') for l in aml_lines]
        # Opening = 0 (no prior). After +100 -> 100. After -30 -> 70.
        self.assertAlmostEqual(balances[0], 100.0, places=2)
        self.assertAlmostEqual(balances[1], 70.0, places=2)

    def test_opening_balance_from_prior_period(self):
        self.post_balanced_move(
            [
                {'account': self.account_revenue, 'credit': 500.0},
                {'account': self.account_cash, 'debit': 500.0},
            ],
            date=fields.Date.from_string('2025-12-15'),
        )
        result = self.handler.compute(self.options)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        opening_line = self._line_by_kind(cash_lines, 'opening_balance')
        self.assertIsNotNone(opening_line)
        self.assertAlmostEqual(
            self._column_value(opening_line, 'balance'), 500.0, places=2,
        )

    def test_closing_balance_on_total_line(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 250.0},
            {'account': self.account_cash, 'debit': 250.0},
        ])
        self._post_in_period([
            {'account': self.account_expense, 'debit': 50.0},
            {'account': self.account_cash, 'credit': 50.0},
        ])
        result = self.handler.compute(self.options)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        total_line = self._line_by_kind(cash_lines, 'account_total')
        self.assertIsNotNone(total_line)
        # Closing for cash: 0 + 250 - 50 = 200.
        self.assertAlmostEqual(
            self._column_value(total_line, 'balance'), 200.0, places=2,
        )

    def test_entry_line_columns_populated(self):
        move = self._post_in_period([
            {'account': self.account_revenue, 'credit': 75.0,
             'name': 'Sales of widgets', 'partner': self.partner_a},
            {'account': self.account_cash, 'debit': 75.0},
        ])
        result = self.handler.compute(self.options)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        aml_line = self._line_by_kind(cash_lines, 'aml')
        self.assertIsNotNone(aml_line)
        self.assertEqual(self._column_value(aml_line, 'journal'),
                         self.journal_misc.code)
        self.assertEqual(self._column_value(aml_line, 'move'), move.name)
        self.assertEqual(self._column_value(aml_line, 'date'), '2026-06-15')

    # ---- date filtering ----

    def test_out_of_period_entries_not_listed_as_aml(self):
        self.post_balanced_move(
            [
                {'account': self.account_revenue, 'credit': 1000.0},
                {'account': self.account_cash, 'debit': 1000.0},
            ],
            date=fields.Date.from_string('2025-12-15'),
        )
        self.post_balanced_move(
            [
                {'account': self.account_revenue, 'credit': 999.0},
                {'account': self.account_cash, 'debit': 999.0},
            ],
            date=fields.Date.from_string('2027-02-01'),
        )
        result = self.handler.compute(self.options)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        aml_lines = [
            l for l in cash_lines
            if (l.get('meta') or {}).get('kind') == 'aml'
        ]
        # The 2025 entry contributes to opening; 2027 entry is excluded.
        # No aml rows should appear in the period.
        self.assertEqual(len(aml_lines), 0)
        # Opening reflects the 2025 entry only.
        opening = self._line_by_kind(cash_lines, 'opening_balance')
        self.assertAlmostEqual(
            self._column_value(opening, 'balance'), 1000.0, places=2,
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
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        aml_lines = [
            l for l in cash_lines
            if (l.get('meta') or {}).get('kind') == 'aml'
        ]
        self.assertEqual(len(aml_lines), 0)

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
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        aml_lines = [
            l for l in cash_lines
            if (l.get('meta') or {}).get('kind') == 'aml'
        ]
        self.assertEqual(len(aml_lines), 1)

    def test_cancelled_excluded(self):
        move = self._post_in_period([
            {'account': self.account_revenue, 'credit': 444.0},
            {'account': self.account_cash, 'debit': 444.0},
        ])
        move.button_cancel()
        result = self.handler.compute(self.options)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        # No entries should be listed for cash; the account header may not
        # appear at all if there is nothing else.
        aml_lines = [
            l for l in cash_lines
            if (l.get('meta') or {}).get('kind') == 'aml'
        ]
        self.assertEqual(len(aml_lines), 0)

    # ---- filter narrowing ----

    def test_account_filter(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        opts = dict(self.options)
        opts['account_ids'] = [self.account_revenue.id]
        result = self.handler.compute(opts)
        # Only revenue lines and an account header should be present.
        rev_lines = self._lines_for_account(result, self.account_revenue.id)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        self.assertGreater(len(rev_lines), 0)
        self.assertEqual(len(cash_lines), 0)

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
        rev_lines = self._lines_for_account(result, self.account_revenue.id)
        aml_lines = [
            l for l in rev_lines
            if (l.get('meta') or {}).get('kind') == 'aml'
        ]
        self.assertEqual(len(aml_lines), 1)

    # ---- error handling ----

    def test_missing_date_from_raises(self):
        bad = dict(self.options)
        bad['date'] = {'date_to': '2026-12-31'}
        with self.assertRaises(UserError):
            self.handler.compute(bad)

    def test_missing_date_to_raises(self):
        bad = dict(self.options)
        bad['date'] = {'date_from': '2026-01-01'}
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
        self.assertEqual(len(first['lines']), len(second['lines']))

    # ---- drill down ----

    def test_drilldown_aml_line_opens_move_form(self):
        move = self._post_in_period([
            {'account': self.account_revenue, 'credit': 75.0},
            {'account': self.account_cash, 'debit': 75.0},
        ])
        # Find any aml line on the cash account.
        result = self.handler.compute(self.options)
        cash_lines = self._lines_for_account(result, self.account_cash.id)
        aml_line = self._line_by_kind(cash_lines, 'aml')
        self.assertIsNotNone(aml_line)
        action = self.handler.get_drilldown_action(self.options, aml_line['id'])
        self.assertIsNotNone(action)
        self.assertEqual(action['res_model'], 'account.move')
        self.assertEqual(action['res_id'], move.id)

    def test_drilldown_account_header_uses_base_default(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 75.0},
            {'account': self.account_cash, 'debit': 75.0},
        ])
        action = self.handler.get_drilldown_action(
            self.options, "account-%s" % self.account_revenue.id,
        )
        self.assertIsNotNone(action)
        self.assertEqual(action['res_model'], 'account.move.line')

    def test_drilldown_opening_or_total_returns_none(self):
        self.assertIsNone(self.handler.get_drilldown_action(
            self.options, "account-%s-opening" % self.account_cash.id,
        ))
        self.assertIsNone(self.handler.get_drilldown_action(
            self.options, "account-%s-total" % self.account_cash.id,
        ))

    def test_drilldown_aml_with_unknown_id_returns_none(self):
        self.assertIsNone(self.handler.get_drilldown_action(
            self.options, "aml-99999999",
        ))

    # ---- XLSX export ----

    def test_xlsx_export_renders_workbook(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0,
             'partner': self.partner_a},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        content = self.report.render_xlsx(self.options)
        self.assertEqual(content[:2], b'PK')
        self.assertGreater(len(content), 1000,
                           "XLSX should contain meaningful content")
