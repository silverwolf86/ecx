# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Cash Flow Statement handler (direct method).

Classifies cash movements into operating, investing, and financing
activities by inspecting the non cash counterparts of each cash affecting
move. The direct method was chosen for v1 because it is more transparent
to SMB readers than the indirect method (which starts from net income and
adjusts), and because it composes naturally with the SQL builder.

Algorithm:

1. Find all moves that have at least one cash account line in the period.
2. For those moves, aggregate non cash line balances by account_type. The
   cash impact attributable to each account_type is SUM(-balance). Because
   each move balances, the sum of -balance over non cash lines equals the
   sum of balance over cash lines.
3. Group account_type buckets into the three activity sections.
4. Add a Net Change line, Opening Cash, Closing Cash, and a Balance Check.

The Balance Check verifies the identity:

    Closing Cash = Opening Cash + Net Change in Cash

If non zero, the underlying ledger has unbalanced postings or there is a
filter inconsistency, and the line surfaces this immediately.

Limitations:

* Only `asset_cash` account_type is considered cash. Credit cards
  (`liability_credit_card`) are treated as financing rather than cash.
  Phase 2 may add a configurable "cash and cash equivalents" set.
* Foreign currency revaluation is mixed in with the activity it affects;
  a more rigorous CFS would isolate FX gains as a non cash adjustment.
"""

from odoo import _, api, fields, models
from odoo.tools import SQL
from odoo.tools.translate import LazyTranslate

from odoo.addons.eh_account_base.tools.sql_builder import MoveLineQuery

_lt = LazyTranslate(__name__)


class EhCashFlowHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.cash_flow'
    _inherit = 'eh.account.dynamic.report.handler.sectioned'
    _description = "Cash Flow Statement report handler"

    REPORT_CODE = 'cash_flow'
    REPORT_NAME = _lt("Cash Flow Statement")

    CASH_TYPES = ('asset_cash',)

    OPERATING_TYPES = (
        'income', 'income_other',
        'expense', 'expense_depreciation', 'expense_direct_cost',
        'asset_receivable', 'liability_payable',
        'asset_current', 'liability_current',
    )
    INVESTING_TYPES = (
        'asset_fixed', 'asset_non_current', 'asset_prepayments',
    )
    FINANCING_TYPES = (
        'liability_non_current', 'liability_credit_card',
        'equity', 'equity_unaffected',
    )

    @api.model
    def _get_account_type_labels(self):
        """Return the per-account-type display label map.

        Returned as a method (not a class attr) so each call resolves
        translations against the active language. A class-level dict
        literal would freeze English strings at module load.
        """
        return {
            'income': _("Income"),
            'income_other': _("Other Income"),
            'expense': _("Expenses"),
            'expense_depreciation': _("Depreciation"),
            'expense_direct_cost': _("Direct Costs"),
            'asset_receivable': _("Receivables"),
            'liability_payable': _("Payables"),
            'asset_current': _("Other Current Assets"),
            'liability_current': _("Other Current Liabilities"),
            'asset_fixed': _("Fixed Assets"),
            'asset_non_current': _("Non Current Assets"),
            'asset_prepayments': _("Prepayments"),
            'liability_non_current': _("Long Term Liabilities"),
            'liability_credit_card': _("Credit Cards"),
            'equity': _("Equity"),
            'equity_unaffected': _("Current Year Earnings"),
        }

    @api.model
    def compute(self, options):
        date_from = self._extract_date(options, 'date_from')
        date_to = self._extract_date(options, 'date_to')
        company_ids = options.get('company_ids') or [self.env.company.id]
        posted_only = bool(options.get('posted_only', True))
        show_zero = bool(options.get('show_zero', False))
        method = (options.get('cash_flow_method') or 'direct').lower()
        if method not in ('direct', 'indirect'):
            method = 'direct'

        cash_move_ids = self._fetch_cash_active_move_ids(
            company_ids=company_ids,
            date_from=date_from, date_to=date_to,
            posted_only=posted_only, options=options,
        )
        impacts_by_type = self._fetch_cash_impacts(
            move_ids=cash_move_ids,
            company_ids=company_ids,
            posted_only=posted_only, options=options,
        ) if cash_move_ids else {}

        investing_total = round(
            self._sum_types(impacts_by_type, self.INVESTING_TYPES), 2,
        )
        financing_total = round(
            self._sum_types(impacts_by_type, self.FINANCING_TYPES), 2,
        )

        if method == 'indirect':
            indirect_breakdown = self._compute_indirect_operating(
                company_ids=company_ids,
                date_from=date_from, date_to=date_to,
                posted_only=posted_only, options=options,
            )
            operating_total = round(indirect_breakdown['total'], 2)
        else:
            indirect_breakdown = None
            operating_total = round(
                self._sum_types(impacts_by_type, self.OPERATING_TYPES), 2,
            )
        net_change = round(
            operating_total + investing_total + financing_total, 2,
        )

        opening_cash = round(self._fetch_cash_balance(
            company_ids=company_ids,
            cutoff_date=date_from, posted_only=posted_only, before=True,
        ), 2)
        closing_cash = round(self._fetch_cash_balance(
            company_ids=company_ids,
            cutoff_date=date_to, posted_only=posted_only, before=False,
        ), 2)
        balance_check = round(
            closing_cash - opening_cash - net_change, 2,
        )

        lines = []
        if method == 'indirect':
            lines.extend(self._render_indirect_operating_section(
                indirect_breakdown, operating_total, show_zero,
            ))
        else:
            lines.extend(self._render_section(
                _("Operating Activities"), 'operating',
                self.OPERATING_TYPES, impacts_by_type,
                section_total=operating_total, show_zero=show_zero,
            ))
        lines.extend(self._render_section(
            _("Investing Activities"), 'investing',
            self.INVESTING_TYPES, impacts_by_type,
            section_total=investing_total, show_zero=show_zero,
        ))
        lines.extend(self._render_section(
            _("Financing Activities"), 'financing',
            self.FINANCING_TYPES, impacts_by_type,
            section_total=financing_total, show_zero=show_zero,
        ))
        lines.append(self._computed_line(
            'net_change_in_cash', _("Net Change in Cash"),
            net_change, kind='net_change',
        ))
        lines.append(self._computed_line(
            'opening_cash_balance', _("Opening Cash Balance"),
            opening_cash, kind='cash_balance',
        ))
        lines.append(self._computed_line(
            'closing_cash_balance', _("Closing Cash Balance"),
            closing_cash, kind='cash_balance',
        ))
        lines.append(self._computed_line(
            'cash_balance_check', _("Balance Check"),
            balance_check, kind='balance_check',
        ))

        return {
            'columns': self._build_two_column_layout(),
            'lines': lines,
            'totals': {
                'operating': operating_total,
                'investing': investing_total,
                'financing': financing_total,
                'net_change_in_cash': net_change,
                'opening_cash_balance': opening_cash,
                'closing_cash_balance': closing_cash,
                'balance_check': balance_check,
            },
            'generated_at': fields.Datetime.now().isoformat(),
            'meta': {
                'report_code': self.REPORT_CODE,
                'date_from': self._iso_date(date_from),
                'date_to': self._iso_date(date_to),
                'company_ids': sorted(int(c) for c in company_ids),
                'posted_only': posted_only,
                'show_zero': show_zero,
                'method': method,
            },
        }

    # ---- internal helpers ----

    def _fetch_cash_active_move_ids(
        self, company_ids, date_from, date_to, posted_only, options,
    ):
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_date_range(date_from=date_from, date_to=date_to)
        query.where_account_types(self.CASH_TYPES)
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)
        # GROUP BY produces unique move_ids without needing DISTINCT.
        query.select_field('move_id')
        query.group_by('move_id')
        return [r['move_id'] for r in query.execute()]

    def _fetch_cash_impacts(
        self, move_ids, company_ids, posted_only, options,
    ):
        if not move_ids:
            return {}
        query = MoveLineQuery(self.env, company_ids=company_ids)
        if posted_only:
            query.where_posted_only()
        query.join_account()
        query.where_raw(SQL("acc.account_type != %s", 'asset_cash'))
        query.where_raw(SQL("aml.move_id IN %s", tuple(move_ids)))
        if options.get('journal_ids'):
            query.where_journals(options['journal_ids'])
        if options.get('partner_ids'):
            query.where_partners(options['partner_ids'])
        if options.get('analytic_account_ids'):
            query.where_analytic_accounts(options['analytic_account_ids'])
        if options.get('analytic_plan_ids'):
            query.where_analytic_plans(options['analytic_plan_ids'])

        query.select_account_field('account_type', alias='account_type')
        query.select(SQL("SUM(-aml.balance)"), 'cash_impact')
        query.group_by(SQL("acc.account_type"))

        rows = query.execute()
        return {
            r['account_type']: float(r['cash_impact'] or 0.0)
            for r in rows
        }

    def _fetch_cash_balance(
        self, company_ids, cutoff_date, posted_only, before,
    ):
        """Sum balance on cash accounts.

        before=True: lines strictly before cutoff_date (used for opening).
        before=False: lines up to and including cutoff_date (closing).
        """
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_account_types(self.CASH_TYPES)
        if posted_only:
            query.where_posted_only()
        if before:
            query.where_raw(SQL("aml.date < %s", cutoff_date))
        else:
            query.where_date_range(date_to=cutoff_date)
        query.select(SQL("COALESCE(SUM(aml.balance), 0)"), 'balance')
        rows = query.execute()
        if not rows:
            return 0.0
        return float(rows[0].get('balance') or 0.0)

    @staticmethod
    def _sum_types(impacts_by_type, types):
        return sum(impacts_by_type.get(t, 0.0) for t in types)

    def _render_section(
        self, name, section_id, types, impacts_by_type,
        section_total, show_zero,
    ):
        lines = [self._section_header_line(name, section_id)]
        type_labels = self._get_account_type_labels()
        for t in types:
            amount = round(impacts_by_type.get(t, 0.0), 2)
            if not show_zero and amount == 0.0:
                continue
            label = type_labels.get(t, t.replace('_', ' ').title())
            lines.append({
                'id': "section-%s-line-%s" % (section_id, t),
                'name': label,
                'level': 1,
                'columns': [
                    {'expression_label': 'amount', 'value': amount},
                ],
                'unfoldable': False,
                'meta': {
                    'kind': 'section_line',
                    'section_id': section_id,
                    'account_type': t,
                },
            })
        lines.append(self._section_total_line(
            _("Total %s") % name, section_total, section_id=section_id,
        ))
        return lines

    # ---- indirect-method helpers ----

    INDIRECT_DEPRECIATION_TYPES = (
        'expense_depreciation',
    )
    INDIRECT_INCOME_TYPES = (
        'income', 'income_other',
    )
    INDIRECT_EXPENSE_TYPES = (
        'expense', 'expense_depreciation', 'expense_direct_cost',
    )
    INDIRECT_WORKING_CAPITAL_TYPES = (
        ('asset_receivable', _lt("Decrease (Increase) in Receivables")),
        ('liability_payable', _lt("Increase (Decrease) in Payables")),
        ('asset_current', _lt(
            "Decrease (Increase) in Other Current Assets",
        )),
        ('liability_current', _lt(
            "Increase (Decrease) in Other Current Liabilities",
        )),
    )

    def _compute_indirect_operating(
        self, company_ids, date_from, date_to, posted_only, options,
    ):
        """Compute the operating-activities section under the indirect
        method.

        Net income for the period
        + Non-cash expenses (depreciation)
        + Working-capital adjustments (-Δ AR, -Δ inventory, +Δ AP)
        = Cash from operating activities

        Returns a dict {'net_income', 'depreciation', 'working_capital',
        'wc_lines', 'total'} so the renderer can show each component
        on its own row.
        """
        income = self._sum_balance_in_period(
            company_ids, self.INDIRECT_INCOME_TYPES,
            date_from, date_to, posted_only, options,
        )
        expense = self._sum_balance_in_period(
            company_ids, self.INDIRECT_EXPENSE_TYPES,
            date_from, date_to, posted_only, options,
        )
        # income posts as a credit (negative balance), expense as a
        # debit (positive). Net income (positive when profitable):
        net_income = -income - expense
        depreciation = self._sum_balance_in_period(
            company_ids, self.INDIRECT_DEPRECIATION_TYPES,
            date_from, date_to, posted_only, options,
        )
        # Working capital changes: opening vs closing balance per type.
        wc_lines = []
        wc_total = 0.0
        for account_type, label in self.INDIRECT_WORKING_CAPITAL_TYPES:
            opening = self._fetch_type_balance(
                company_ids, account_type, date_from,
                posted_only, before=True,
            )
            closing = self._fetch_type_balance(
                company_ids, account_type, date_to,
                posted_only, before=False,
            )
            delta = closing - opening
            # An increase in AR uses cash (-delta);
            # an increase in AP provides cash (+delta).
            if account_type in ('asset_receivable', 'asset_current'):
                cash_effect = -delta
            else:
                cash_effect = delta
            wc_lines.append({
                'account_type': account_type,
                'label': str(label),
                'amount': round(cash_effect, 2),
            })
            wc_total += cash_effect
        total = net_income + depreciation + wc_total
        return {
            'net_income': round(net_income, 2),
            'depreciation': round(depreciation, 2),
            'working_capital': round(wc_total, 2),
            'wc_lines': wc_lines,
            'total': round(total, 2),
        }

    def _sum_balance_in_period(
        self, company_ids, account_types, date_from, date_to,
        posted_only, options,
    ):
        if not account_types:
            return 0.0
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_date_range(date_from=date_from, date_to=date_to)
        query.where_account_types(account_types)
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)
        query.select(SQL("COALESCE(SUM(aml.balance), 0)"), 'balance')
        rows = query.execute()
        return float(rows[0].get('balance') or 0.0) if rows else 0.0

    def _fetch_type_balance(
        self, company_ids, account_type, cutoff_date, posted_only, before,
    ):
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_account_types((account_type,))
        if posted_only:
            query.where_posted_only()
        if before:
            query.where_raw(SQL("aml.date < %s", cutoff_date))
        else:
            query.where_date_range(date_to=cutoff_date)
        query.select(SQL("COALESCE(SUM(aml.balance), 0)"), 'balance')
        rows = query.execute()
        return float(rows[0].get('balance') or 0.0) if rows else 0.0

    def _render_indirect_operating_section(
        self, breakdown, section_total, show_zero,
    ):
        section_id = 'operating'
        lines = [self._section_header_line(
            _("Operating Activities (indirect method)"), section_id,
        )]
        lines.append({
            'id': 'indirect-net-income',
            'name': _("Net income for the period"),
            'level': 1,
            'columns': [{
                'expression_label': 'amount',
                'value': breakdown['net_income'],
            }],
            'unfoldable': False,
            'meta': {'kind': 'section_line', 'section_id': section_id},
        })
        if show_zero or breakdown['depreciation'] != 0.0:
            lines.append({
                'id': 'indirect-depreciation',
                'name': _("Add back: depreciation and amortisation"),
                'level': 1,
                'columns': [{
                    'expression_label': 'amount',
                    'value': breakdown['depreciation'],
                }],
                'unfoldable': False,
                'meta': {'kind': 'section_line', 'section_id': section_id},
            })
        for wc in breakdown['wc_lines']:
            if not show_zero and wc['amount'] == 0.0:
                continue
            lines.append({
                'id': 'indirect-wc-%s' % wc['account_type'],
                'name': wc['label'],
                'level': 1,
                'columns': [{
                    'expression_label': 'amount',
                    'value': wc['amount'],
                }],
                'unfoldable': False,
                'meta': {
                    'kind': 'section_line',
                    'section_id': section_id,
                    'account_type': wc['account_type'],
                },
            })
        lines.append(self._section_total_line(
            _("Net cash from operating activities"),
            section_total, section_id=section_id,
        ))
        return lines
