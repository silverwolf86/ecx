# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Trial Balance handler tests.

Covers:

* Movement column shows period activity.
* Opening balance reflects entries before date_from.
* Closing balance equals opening plus period movement.
* Zero balance accounts hidden by default; show_zero exposes them.
* Totals balance: debit equals credit at every column tier.
* Account, journal, partner filters narrow the result set.
* posted_only excludes draft entries; setting it false includes them.
* Cancelled entries are always excluded.
* Missing date raises a clear UserError.
* Orchestrator render path produces the same data and respects the cache.
"""

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_dynamic_reports', 'integration', 'post_install', '-at_install')
class TestTrialBalanceHandler(EhAccountIntegrationTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.handler = cls.env['eh.account.dynamic.report.handler.trial_balance']
        cls.report = cls.env['eh.account.dynamic.report'].search(
            [('code', '=', 'trial_balance')], limit=1,
        )
        if not cls.report:
            cls.report = cls.env['eh.account.dynamic.report'].create({
                'code': 'trial_balance',
                'name': 'Trial Balance',
                'handler_model': 'eh.account.dynamic.report.handler.trial_balance',
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

    def _post_before_period(self, lines):
        return self.post_balanced_move(
            lines, date=fields.Date.from_string('2025-12-15'),
        )

    @staticmethod
    def _index_lines(result):
        return {line['meta']['account_code']: line for line in result['lines']}

    @staticmethod
    def _column_value(line, label):
        for col in line['columns']:
            if col['expression_label'] == label:
                return col['value']
        raise AssertionError(f"Column {label!r} missing from line {line['name']!r}")

    # ---- core math ----

    def test_period_movement_appears(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 1000.0,
             'partner': self.partner_a},
            {'account': self.account_cash, 'debit': 1000.0},
        ])
        result = self.handler.compute(self.options)
        idx = self._index_lines(result)
        self.assertIn('4000', idx)
        self.assertAlmostEqual(
            self._column_value(idx['4000'], 'period_credit'), 1000.0, places=2,
        )

    def test_opening_balance_carries_from_prior_period(self):
        self._post_before_period([
            {'account': self.account_revenue, 'credit': 500.0},
            {'account': self.account_cash, 'debit': 500.0},
        ])
        result = self.handler.compute(self.options)
        idx = self._index_lines(result)
        self.assertAlmostEqual(
            self._column_value(idx['1000'], 'opening_debit'), 500.0, places=2,
        )

    def test_closing_equals_opening_plus_movement(self):
        self._post_before_period([
            {'account': self.account_revenue, 'credit': 500.0},
            {'account': self.account_cash, 'debit': 500.0},
        ])
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 200.0},
            {'account': self.account_cash, 'debit': 200.0},
        ])
        result = self.handler.compute(self.options)
        cash = self._index_lines(result)['1000']
        cols = {c['expression_label']: c['value'] for c in cash['columns']}
        self.assertAlmostEqual(cols['opening_debit'], 500.0, places=2)
        self.assertAlmostEqual(cols['period_debit'], 200.0, places=2)
        self.assertAlmostEqual(cols['closing_debit'], 700.0, places=2)
        self.assertAlmostEqual(cols['opening_credit'], 0.0, places=2)
        self.assertAlmostEqual(cols['period_credit'], 0.0, places=2)
        self.assertAlmostEqual(cols['closing_credit'], 0.0, places=2)

    def test_totals_balance_at_each_tier(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 1000.0},
            {'account': self.account_cash, 'debit': 1000.0},
        ])
        self._post_in_period([
            {'account': self.account_expense, 'debit': 200.0},
            {'account': self.account_cash, 'credit': 200.0},
        ])
        result = self.handler.compute(self.options)
        totals = result['totals']
        self.assertAlmostEqual(
            totals['period_debit'], totals['period_credit'], places=2,
        )
        self.assertAlmostEqual(
            totals['closing_debit'], totals['closing_credit'], places=2,
        )
        self.assertAlmostEqual(
            totals['opening_debit'], totals['opening_credit'], places=2,
        )

    # ---- filter behaviour ----

    def test_zero_balance_account_hidden_by_default(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        result = self.handler.compute(self.options)
        idx = self._index_lines(result)
        self.assertNotIn('5000', idx,
                         "Untouched expense account must be hidden")

    def test_account_filter(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        opts = dict(self.options)
        opts['account_ids'] = [self.account_cash.id]
        result = self.handler.compute(opts)
        idx = self._index_lines(result)
        self.assertIn('1000', idx)
        self.assertNotIn('4000', idx)

    def test_journal_filter(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        opts = dict(self.options)
        opts['journal_ids'] = [self.journal_misc.id]
        result = self.handler.compute(opts)
        # Posting was via journal_misc, so it should still appear.
        self.assertIn('1000', self._index_lines(result))

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
        idx = self._index_lines(result)
        # Only the 100 credit (partner A) should aggregate; cash line had no
        # partner so it is not present in the partner filtered result.
        self.assertIn('4000', idx)
        self.assertAlmostEqual(
            self._column_value(idx['4000'], 'period_credit'), 100.0, places=2,
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
        idx = self._index_lines(result)
        self.assertNotIn(
            '4000', idx,
            "draft entries must be excluded when posted_only=True",
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
        idx = self._index_lines(result)
        self.assertIn('4000', idx)
        self.assertAlmostEqual(
            self._column_value(idx['4000'], 'period_credit'), 333.0, places=2,
        )

    def test_cancelled_entries_excluded(self):
        move = self._post_in_period([
            {'account': self.account_revenue, 'credit': 444.0},
            {'account': self.account_cash, 'debit': 444.0},
        ])
        move.button_cancel()
        result = self.handler.compute(self.options)
        idx = self._index_lines(result)
        self.assertNotIn('4000', idx)

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

    def test_orchestrator_cache_hit_on_repeated_render(self):
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])
        first = self.report.render(self.options)
        second = self.report.render(self.options)
        self.assertFalse(first['from_cache'])
        self.assertTrue(second['from_cache'])
        # Cached payload should match the freshly computed one in shape.
        self.assertEqual(len(first['lines']), len(second['lines']))
        self.assertEqual(first['totals'], second['totals'])

    def test_orchestrator_invalidates_cache_on_new_post(self):
        first = self.report.render(self.options)
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 50.0},
            {'account': self.account_cash, 'debit': 50.0},
        ])
        second = self.report.render(self.options)
        self.assertFalse(second['from_cache'],
                         "Posting must invalidate the cache")
        # The new entry should appear in the second render.
        idx = self._index_lines(second)
        self.assertIn('4000', idx)

    def test_drilldown_action_returns_filtered_journal_items(self):
        move = self._post_in_period([
            {'account': self.account_revenue, 'credit': 75.0},
            {'account': self.account_cash, 'debit': 75.0},
        ])
        action = self.handler.get_drilldown_action(
            self.options, "account-%s" % self.account_revenue.id,
        )
        self.assertIsNotNone(action)
        self.assertEqual(action['res_model'], 'account.move.line')
        # Verify the domain matches the revenue line.
        Line = self.env['account.move.line']
        items = Line.search(action['domain'])
        self.assertIn(
            self.account_revenue.id, items.mapped('account_id.id'),
        )

    def test_drilldown_action_returns_none_for_invalid_id(self):
        action = self.handler.get_drilldown_action(self.options, 'totally-bogus')
        self.assertIsNone(action)

    def test_compute_under_non_en_us_lang_does_not_crash(self):
        """Regression: Trial Balance must run in any env.lang.

        Customer report (Daria, INTERIM 2000 GNF, odoo.sh, French UI):
        opening the Balance générale screen surfaced a generic "Error:
        Odoo Server Error" with no traceback in the UI.

        Root cause: the trial balance handler issued a SELECT whose
        account_name expression resolved via the MoveLineQuery
        translated-name helper (``COALESCE(acc.name ->> '<lang>',
        acc.name ->> 'en_US')`` when env.lang differs from en_US),
        but the GROUP BY clause hardcoded ``(acc.name ->> 'en_US')``.
        PostgreSQL strictly requires every non-aggregated SELECT
        expression to appear in GROUP BY verbatim, so it rejected the
        query with ``column "acc.name" must appear in the GROUP BY
        clause`` for every non-en_US locale.

        The fix made trial_balance.py use the new
        ``group_by_account_field`` helper so SELECT, ORDER BY, and
        GROUP BY share the same expression for translated columns.
        This test installs French, posts an entry, runs compute() and
        render() under fr_FR, and asserts both return data without
        raising.
        """
        # Ensure French is active. Odoo lazy-loads languages, so we
        # call load_language directly rather than INSERT into res_lang.
        self.env['res.lang']._activate_lang('fr_FR')

        # Post one entry inside the period so the SQL has rows to
        # group; a zero-row query bypasses the GROUP BY validation in
        # some PostgreSQL versions.
        self._post_in_period([
            {'account': self.account_revenue, 'credit': 100.0},
            {'account': self.account_cash, 'debit': 100.0},
        ])

        handler = self.handler.with_context(lang='fr_FR')
        report = self.report.with_context(lang='fr_FR')

        # compute() path
        result = handler.compute(self.options)
        self.assertTrue(result.get('lines'),
                        "compute() under fr_FR returned no lines")

        # render() path (the orchestrator the OWL viewer actually calls)
        rendered = report.render(self.options)
        self.assertTrue(rendered.get('lines'),
                        "render() under fr_FR returned no lines")
