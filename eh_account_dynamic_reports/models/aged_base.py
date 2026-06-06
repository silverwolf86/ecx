# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Base for aged receivable / payable reports.

Aged reports answer: "as of date_to, what is each partner's open balance,
broken into aging buckets by days overdue?" The bucket layout is fixed at
five tiers (Not Due, 0 to 30, 31 to 60, 61 to 90, 91 plus) which matches
the convention used by the AU, NZ, UK, and GCC markets.

Subclasses set:

* ACCOUNT_TYPES: tuple of account_type strings to include.
* SIGN: +1 for receivable (positive amounts owed to us), -1 for payable
  (positive amounts we owe).

The handler then:

1. Fetches per line data: partner_id, due date, balance, amount_residual,
   journal, move name, label.
2. Filters to lines whose amount_residual is non zero (still open in
   today's reconciliation state, see Phase 2 note below).
3. Filters to date <= date_to (the line existed by the report date).
4. Aggregates open residuals per partner into the five buckets, classifying
   each line by days overdue (date_to minus due_date if set, otherwise
   minus posting date).
5. Renders one row per partner with seven monetary columns and a final
   Totals row.

Historical accuracy: the residual is recomputed as of date_to by
rewinding every partial reconciliation whose create_date falls after
date_to. A back-dated aged report therefore reflects what was open on
that date, not what is open today. The rewind uses a correlated subquery
on account.partial.reconcile filtered to create_date <= date_to.
"""

import datetime

from odoo import _, api, fields, models
from odoo.tools import SQL

from odoo.addons.eh_account_base.tools.sql_builder import MoveLineQuery


# Five fixed buckets. Tuple format: (key, label, day_min, day_max).
# day_min is inclusive, day_max is inclusive. Negative days_overdue means
# the line is not yet due, so it lands in the 'not_due' bucket.
_BUCKETS = (
    ('not_due', "Not Due", None, 0),
    ('bucket_30', "0 to 30 Days", 1, 30),
    ('bucket_60', "31 to 60 Days", 31, 60),
    ('bucket_90', "61 to 90 Days", 61, 90),
    ('bucket_older', "91 Plus Days", 91, None),
)


class EhAgedBaseHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.aged_base'
    _inherit = 'eh.account.dynamic.report.handler'
    _description = "Base for Aged Receivable / Payable handlers"

    ACCOUNT_TYPES = ()
    SIGN = 1

    @api.model
    def compute(self, options):
        date_to = self._extract_date(options, 'date_to')
        company_ids = options.get('company_ids') or [self.env.company.id]
        posted_only = bool(options.get('posted_only', True))
        show_zero = bool(options.get('show_zero', False))

        rows = self._fetch_open_lines(
            company_ids=company_ids, date_to=date_to,
            posted_only=posted_only, options=options,
        )
        partner_buckets = self._aggregate_into_buckets(rows, date_to)

        lines, totals = self._build_lines_and_totals(
            partner_buckets, show_zero,
        )

        return {
            'columns': self._build_columns(),
            'lines': lines,
            'totals': totals,
            'generated_at': fields.Datetime.now().isoformat(),
            'meta': {
                'report_code': self.REPORT_CODE,
                'date_to': self._iso_date(date_to),
                'company_ids': sorted(int(c) for c in company_ids),
                'posted_only': posted_only,
                'show_zero': show_zero,
            },
        }

    @api.model
    def get_drilldown_action(self, options, line_id):
        """partner-N opens the journal items list filtered to the partner
        and account types of this aged report. Other ids return None.
        """
        if not line_id or not line_id.startswith('partner-'):
            return None
        rest = line_id.split('-', 1)[1]
        if not rest.isdigit():
            return None
        partner_id = int(rest)
        try:
            date_to = self._extract_date(options, 'date_to')
        except Exception:
            return None
        company_ids = options.get('company_ids') or [self.env.company.id]
        domain = [
            ('partner_id', '=', partner_id),
            ('company_id', 'in', list(company_ids)),
            ('date', '<=', self._iso_date(date_to)),
            ('account_id.account_type', 'in', list(self.ACCOUNT_TYPES)),
            ('amount_residual', '!=', 0),
        ]
        if options.get('posted_only', True):
            domain.append(('parent_state', '=', 'posted'))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Open Items"),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
        }

    # ---- internal helpers ----

    def _build_columns(self):
        return [
            {'expression_label': 'partner', 'name': _("Partner"),
             'figure_type': 'string'},
            {'expression_label': 'not_due', 'name': _("Not Due"),
             'figure_type': 'monetary'},
            {'expression_label': 'bucket_30', 'name': _("0 to 30 Days"),
             'figure_type': 'monetary'},
            {'expression_label': 'bucket_60', 'name': _("31 to 60 Days"),
             'figure_type': 'monetary'},
            {'expression_label': 'bucket_90', 'name': _("61 to 90 Days"),
             'figure_type': 'monetary'},
            {'expression_label': 'bucket_older', 'name': _("91 Plus Days"),
             'figure_type': 'monetary'},
            {'expression_label': 'total', 'name': _("Total"),
             'figure_type': 'monetary'},
        ]

    def _fetch_open_lines(
        self, company_ids, date_to, posted_only, options,
    ):
        if not self.ACCOUNT_TYPES:
            raise ValueError(
                "%s.ACCOUNT_TYPES is empty; subclass must override."
                % type(self).__name__,
            )
        # Compute the residual *as of date_to* by reversing every partial
        # reconciliation whose create_date is later than date_to. A line
        # that was open on date_to but has since been settled now shows a
        # zero amount_residual; without this rewind the historical aged
        # report would drop it. The expression mirrors Odoo's residual
        # computation: balance minus matched-debit-side plus matched-
        # credit-side, scoped to reconciliations posted on or before
        # date_to.
        historical_residual = SQL("""(
            aml.balance
            - COALESCE((
                SELECT SUM(apr.amount)
                FROM account_partial_reconcile apr
                WHERE apr.debit_move_id = aml.id
                  AND apr.create_date::date <= %s
            ), 0)
            + COALESCE((
                SELECT SUM(apr.amount)
                FROM account_partial_reconcile apr
                WHERE apr.credit_move_id = aml.id
                  AND apr.create_date::date <= %s
            ), 0)
        )""", date_to, date_to)

        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_date_range(date_to=date_to)
        query.where_account_types(self.ACCOUNT_TYPES)
        # Keep only lines whose historical residual is non zero. Wrap in
        # a CTE-style filter via where_raw so the same expression drives
        # both the WHERE and the SELECT. Reusing SQL keeps the binding
        # params consistent.
        residual_filter = SQL("""(
            aml.balance
            - COALESCE((
                SELECT SUM(apr.amount)
                FROM account_partial_reconcile apr
                WHERE apr.debit_move_id = aml.id
                  AND apr.create_date::date <= %s
            ), 0)
            + COALESCE((
                SELECT SUM(apr.amount)
                FROM account_partial_reconcile apr
                WHERE apr.credit_move_id = aml.id
                  AND apr.create_date::date <= %s
            ), 0)
        ) <> 0""", date_to, date_to)
        query.where_raw(residual_filter)
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)

        query.select_field('id', alias='aml_id')
        query.select_field('partner_id')
        query.select_field('date')
        query.select_field('date_maturity')
        query.select(historical_residual, 'amount_residual')
        query.join_partner()
        query.select(SQL("p.name"), 'partner_name')
        return query.execute()

    def _aggregate_into_buckets(self, rows, date_to):
        """Return a dict {partner_id: {bucket_key: amount, ..., 'total': X,
        'partner_name': str}}.
        """
        partner_buckets = {}
        for row in rows:
            partner_id = row.get('partner_id')
            if not partner_id:
                # Lines without a partner are skipped; aged reports are
                # partner centric.
                continue

            line_date = row.get('date')
            if isinstance(line_date, str):
                line_date = datetime.date.fromisoformat(line_date[:10])
            due_date = row.get('date_maturity') or line_date
            if isinstance(due_date, str):
                due_date = datetime.date.fromisoformat(due_date[:10])
            days_overdue = (date_to - due_date).days

            bucket_key = self._classify_bucket(days_overdue)
            amount = float(row.get('amount_residual') or 0.0) * self.SIGN

            if partner_id not in partner_buckets:
                partner_buckets[partner_id] = {
                    'partner_name': row.get('partner_name') or '',
                    'not_due': 0.0,
                    'bucket_30': 0.0,
                    'bucket_60': 0.0,
                    'bucket_90': 0.0,
                    'bucket_older': 0.0,
                }
            partner_buckets[partner_id][bucket_key] += amount

        return partner_buckets

    @staticmethod
    def _classify_bucket(days_overdue):
        for key, _label, day_min, day_max in _BUCKETS:
            if day_min is None and days_overdue <= day_max:
                return key
            if day_max is None and days_overdue >= day_min:
                return key
            if day_min is not None and day_max is not None:
                if day_min <= days_overdue <= day_max:
                    return key
        return 'bucket_older'

    def _build_lines_and_totals(self, partner_buckets, show_zero):
        totals = {
            'not_due': 0.0, 'bucket_30': 0.0,
            'bucket_60': 0.0, 'bucket_90': 0.0,
            'bucket_older': 0.0, 'total': 0.0,
        }
        sorted_partner_ids = sorted(
            partner_buckets.keys(),
            key=lambda pid: partner_buckets[pid]['partner_name'].lower(),
        )

        lines = []
        for partner_id in sorted_partner_ids:
            buckets = partner_buckets[partner_id]
            row_total = round(
                buckets['not_due'] + buckets['bucket_30']
                + buckets['bucket_60'] + buckets['bucket_90']
                + buckets['bucket_older'], 2,
            )
            sum_all = abs(buckets['not_due']) + abs(buckets['bucket_30']) + \
                abs(buckets['bucket_60']) + abs(buckets['bucket_90']) + \
                abs(buckets['bucket_older'])
            if not show_zero and sum_all == 0.0:
                continue

            lines.append({
                'id': "partner-%s" % partner_id,
                'name': buckets['partner_name'] or "(no name)",
                'level': 1,
                'columns': [
                    {'expression_label': 'not_due',
                     'value': round(buckets['not_due'], 2)},
                    {'expression_label': 'bucket_30',
                     'value': round(buckets['bucket_30'], 2)},
                    {'expression_label': 'bucket_60',
                     'value': round(buckets['bucket_60'], 2)},
                    {'expression_label': 'bucket_90',
                     'value': round(buckets['bucket_90'], 2)},
                    {'expression_label': 'bucket_older',
                     'value': round(buckets['bucket_older'], 2)},
                    {'expression_label': 'total', 'value': row_total},
                ],
                'unfoldable': False,
                'meta': {'kind': 'partner_aged', 'partner_id': partner_id},
            })

            totals['not_due'] += buckets['not_due']
            totals['bucket_30'] += buckets['bucket_30']
            totals['bucket_60'] += buckets['bucket_60']
            totals['bucket_90'] += buckets['bucket_90']
            totals['bucket_older'] += buckets['bucket_older']
            totals['total'] += row_total

        totals = {k: round(v, 2) for k, v in totals.items()}
        return lines, totals
