# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Trial Balance handler.

Single SQL pass. Conditional aggregation splits the same set of journal
lines into three buckets per account in one scan:

* opening_balance: lines whose date is strictly before date_from.
* period_debit and period_credit: lines whose date falls within
  [date_from, date_to].

Closing balance is then derived in Python as
opening_balance + period_debit - period_credit. The split into debit and
credit display columns happens at presentation time based on the sign of
the underlying balance, which matches accounting convention.

The handler honours all standard filters (companies, journals, partners,
accounts, posted_only, show_zero) by composing them through MoveLineQuery,
so SQL safety, multi company scoping, and cancelled exclusion are inherited
automatically.
"""

from odoo import _, api, fields, models
from odoo.tools import SQL
from odoo.tools.translate import LazyTranslate

from odoo.addons.eh_account_base.tools.sql_builder import MoveLineQuery

_lt = LazyTranslate(__name__)


class EhTrialBalanceHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.trial_balance'
    _inherit = 'eh.account.dynamic.report.handler'
    _description = "Trial Balance report handler"

    REPORT_CODE = 'trial_balance'
    REPORT_NAME = _lt("Trial Balance")

    @api.model
    def compute(self, options):
        date_from = self._extract_date(options, 'date_from')
        date_to = self._extract_date(options, 'date_to')
        company_ids = options.get('company_ids') or [self.env.company.id]
        posted_only = bool(options.get('posted_only', True))
        show_zero = bool(options.get('show_zero', False))
        hierarchical = bool(options.get('hierarchical_groups', True))
        unfolded_ids = set(options.get('unfolded_lines') or [])
        rows = self._fetch_account_buckets(
            company_ids=company_ids,
            date_from=date_from,
            date_to=date_to,
            posted_only=posted_only,
            options=options,
        )

        if hierarchical:
            lines, totals = self._build_hierarchical_lines_and_totals(
                rows, show_zero, unfolded_ids,
            )
        else:
            lines, totals = self._build_lines_and_totals(rows, show_zero)

        return {
            'columns': self._build_columns(),
            'lines': lines,
            'totals': totals,
            'generated_at': fields.Datetime.now().isoformat(),
            'meta': {
                'report_code': self.REPORT_CODE,
                'date_from': self._iso_date(date_from),
                'date_to': self._iso_date(date_to),
                'company_ids': sorted(int(c) for c in company_ids),
                'posted_only': posted_only,
                'show_zero': show_zero,
                'hierarchical_groups': hierarchical,
            },
        }

    # Drill down behaviour comes from the base handler; the default impl
    # already opens filtered journal items for any line whose id is
    # 'account-N'. Trial Balance follows that scheme exactly.

    # ---- internal helpers ----

    def _build_columns(self):
        return [
            {'expression_label': 'account', 'name': _("Account"),
             'figure_type': 'string'},
            {'expression_label': 'opening_debit', 'name': _("Opening DB"),
             'figure_type': 'monetary'},
            {'expression_label': 'opening_credit', 'name': _("Opening CR"),
             'figure_type': 'monetary'},
            {'expression_label': 'period_debit', 'name': _("Movement DB"),
             'figure_type': 'monetary'},
            {'expression_label': 'period_credit', 'name': _("Movement CR"),
             'figure_type': 'monetary'},
            {'expression_label': 'closing_debit', 'name': _("Closing DB"),
             'figure_type': 'monetary'},
            {'expression_label': 'closing_credit', 'name': _("Closing CR"),
             'figure_type': 'monetary'},
        ]

    def _fetch_account_buckets(
        self, company_ids, date_from, date_to, posted_only, options,
    ):
        query = MoveLineQuery(self.env, company_ids=company_ids)
        # Lines up to date_to participate. We need everything before
        # date_from for the opening balance plus everything in the period
        # for the movement columns.
        query.where_date_range(date_to=date_to)
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)

        query.select_field('account_id')
        query.select_account_field('code', alias='account_code')
        query.select_account_field('name', alias='account_name')
        query.select(
            SQL("SUM(CASE WHEN aml.date < %s THEN aml.balance ELSE 0 END)",
                date_from),
            'opening_balance',
        )
        query.select(
            SQL(
                "SUM(CASE WHEN aml.date >= %s AND aml.date <= %s "
                "THEN aml.debit ELSE 0 END)",
                date_from, date_to,
            ),
            'period_debit',
        )
        query.select(
            SQL(
                "SUM(CASE WHEN aml.date >= %s AND aml.date <= %s "
                "THEN aml.credit ELSE 0 END)",
                date_from, date_to,
            ),
            'period_credit',
        )
        # Group by all non aggregated SELECT expressions for portability.
        # The account_code and account_name expressions are resolved via the
        # MoveLineQuery helpers so GROUP BY matches SELECT verbatim, including
        # the per-language COALESCE branch on translated jsonb columns. A
        # mismatch here (e.g. hardcoding ``en_US`` in GROUP BY while SELECT
        # uses COALESCE for a non-en_US env.lang) causes PostgreSQL to
        # reject the query with "must appear in the GROUP BY clause", which
        # surfaces to the user as a generic "Odoo Server Error" with no
        # actionable detail. Keep the three call sites symmetric.
        query.group_by(SQL("aml.account_id"))
        query.group_by_account_field('code')
        query.group_by_account_field('name')
        query.order_by_account_field('code', 'ASC')
        return query.execute()

    def _build_lines_and_totals(self, rows, show_zero):
        lines = []
        totals = {
            'opening_debit': 0.0, 'opening_credit': 0.0,
            'period_debit': 0.0, 'period_credit': 0.0,
            'closing_debit': 0.0, 'closing_credit': 0.0,
        }
        for row in rows:
            opening = float(row.get('opening_balance') or 0.0)
            period_debit = float(row.get('period_debit') or 0.0)
            period_credit = float(row.get('period_credit') or 0.0)
            closing = opening + period_debit - period_credit

            opening_debit = opening if opening > 0 else 0.0
            opening_credit = -opening if opening < 0 else 0.0
            closing_debit = closing if closing > 0 else 0.0
            closing_credit = -closing if closing < 0 else 0.0

            sum_all = (opening_debit + opening_credit + period_debit
                       + period_credit + closing_debit + closing_credit)
            if not show_zero and sum_all == 0.0:
                continue

            lines.append({
                'id': "account-%s" % row['account_id'],
                'name': "%s %s" % (row['account_code'], row['account_name']),
                'level': 1,
                'columns': [
                    {'expression_label': 'opening_debit',
                     'value': round(opening_debit, 2)},
                    {'expression_label': 'opening_credit',
                     'value': round(opening_credit, 2)},
                    {'expression_label': 'period_debit',
                     'value': round(period_debit, 2)},
                    {'expression_label': 'period_credit',
                     'value': round(period_credit, 2)},
                    {'expression_label': 'closing_debit',
                     'value': round(closing_debit, 2)},
                    {'expression_label': 'closing_credit',
                     'value': round(closing_credit, 2)},
                ],
                'unfoldable': False,
                'meta': {
                    'account_id': row['account_id'],
                    'account_code': row['account_code'],
                },
            })

            totals['opening_debit'] += opening_debit
            totals['opening_credit'] += opening_credit
            totals['period_debit'] += period_debit
            totals['period_credit'] += period_credit
            totals['closing_debit'] += closing_debit
            totals['closing_credit'] += closing_credit

        totals = {k: round(v, 2) for k, v in totals.items()}
        return lines, totals

    def _build_hierarchical_lines_and_totals(
        self, rows, show_zero, unfolded_ids,
    ):
        """Multi-column hierarchical builder for Trial Balance.

        Computes the per-account 6-column tuple in Python first
        (opening_db / cr, period_db / cr, closing_db / cr), then walks
        account.account.group_id and account.group.parent_id to build
        the nested line list with parent_id linkage. Group totals are
        the sum of every descendant account's column tuple.

        Mirrors the shape of _render_account_lines_grouped on the
        sectioned base but is multi-column-aware and lives here
        because Trial Balance is the only multi-column report whose
        grouping aggregates across columns.
        """
        if not rows:
            return [], {
                'opening_debit': 0.0, 'opening_credit': 0.0,
                'period_debit': 0.0, 'period_credit': 0.0,
                'closing_debit': 0.0, 'closing_credit': 0.0,
            }
        # Per-account computed columns (six values each).
        per_account = {}
        for row in rows:
            opening = float(row.get('opening_balance') or 0.0)
            period_debit = float(row.get('period_debit') or 0.0)
            period_credit = float(row.get('period_credit') or 0.0)
            closing = opening + period_debit - period_credit
            opening_debit = opening if opening > 0 else 0.0
            opening_credit = -opening if opening < 0 else 0.0
            closing_debit = closing if closing > 0 else 0.0
            closing_credit = -closing if closing < 0 else 0.0
            sum_all = (
                opening_debit + opening_credit
                + period_debit + period_credit
                + closing_debit + closing_credit
            )
            if not show_zero and sum_all == 0.0:
                continue
            per_account[row['account_id']] = {
                'code': row['account_code'],
                'name': row['account_name'],
                'opening_debit': opening_debit,
                'opening_credit': opening_credit,
                'period_debit': period_debit,
                'period_credit': period_credit,
                'closing_debit': closing_debit,
                'closing_credit': closing_credit,
            }
        if not per_account:
            return [], {
                'opening_debit': 0.0, 'opening_credit': 0.0,
                'period_debit': 0.0, 'period_credit': 0.0,
                'closing_debit': 0.0, 'closing_credit': 0.0,
            }

        # Resolve group path per account. Reuses the same logic as
        # the sectioned helper.
        Account = self.env['account.account'].sudo()
        Group = self.env['account.group'].sudo()
        accounts = Account.browse(list(per_account.keys()))
        group_paths = {}
        for acc in accounts:
            chain = []
            grp = acc.group_id
            while grp:
                chain.append(grp.id)
                grp = grp.parent_id
            chain.reverse()
            group_paths[acc.id] = tuple(chain)

        # Aggregate per group (every prefix of every account's path).
        zero = {
            'opening_debit': 0.0, 'opening_credit': 0.0,
            'period_debit': 0.0, 'period_credit': 0.0,
            'closing_debit': 0.0, 'closing_credit': 0.0,
        }
        group_totals = {}
        accounts_by_group = {}
        for acc_id, vals in per_account.items():
            path = group_paths[acc_id]
            cumulative = ()
            for gid in path:
                cumulative = cumulative + (gid,)
                bucket = group_totals.setdefault(cumulative, dict(zero))
                for k in zero:
                    bucket[k] += vals[k]
            accounts_by_group.setdefault(path, []).append(acc_id)

        # Path identifiers and ordering.
        section_id = 'trial_balance'

        def _line_id_for_path(path_tuple):
            if not path_tuple:
                return "section-%s-header" % section_id
            return "section-%s-group-%s" % (
                section_id,
                "_".join(str(g) for g in path_tuple),
            )

        all_paths = set()
        for parent_path in accounts_by_group:
            cumulative = ()
            for g in parent_path:
                cumulative = cumulative + (g,)
                all_paths.add(cumulative)

        def _path_sort_key(p):
            keys = []
            for gid in p:
                grp = Group.browse(gid)
                keys.append((grp.code_prefix_start or '', gid))
            return keys
        ordered_paths = sorted(all_paths, key=_path_sort_key)

        lines = []
        # Ungrouped accounts attach directly under a synthetic header
        # at the top, matching the sectioned helper's behaviour.
        ungrouped = accounts_by_group.get((), [])
        if ungrouped:
            ungrouped.sort(key=lambda a: per_account[a]['code'] or '')
            for aid in ungrouped:
                vals = per_account[aid]
                lines.append(self._tb_account_line(aid, vals, level=1, parent_id=None))

        for path in ordered_paths:
            grp = Group.browse(path[-1])
            depth = len(path)
            parent_id = _line_id_for_path(path[:-1]) if len(path) > 1 else None
            this_id = _line_id_for_path(path)
            unfolded = (not unfolded_ids) or this_id in unfolded_ids
            totals_at_path = group_totals[path]
            lines.append({
                'id': this_id,
                'name': "%s %s" % (
                    grp.code_prefix_start or '',
                    grp.display_name or grp.name or '',
                ),
                'level': depth,
                'parent_id': parent_id,
                'columns': [
                    {'expression_label': k,
                     'value': round(totals_at_path[k], 2)}
                    for k in ('opening_debit', 'opening_credit',
                              'period_debit', 'period_credit',
                              'closing_debit', 'closing_credit')
                ],
                'unfoldable': True,
                'unfolded': unfolded,
                'meta': {
                    'kind': 'account_group',
                    'group_id': grp.id,
                    'depth': depth,
                },
            })
            for aid in sorted(
                accounts_by_group.get(path, []),
                key=lambda a: per_account[a]['code'] or '',
            ):
                vals = per_account[aid]
                lines.append(self._tb_account_line(
                    aid, vals, level=depth + 1, parent_id=this_id,
                ))

        # Top-level totals across every account in the report.
        totals = {k: 0.0 for k in zero}
        for vals in per_account.values():
            for k in totals:
                totals[k] += vals[k]
        totals = {k: round(v, 2) for k, v in totals.items()}
        return lines, totals

    @staticmethod
    def _tb_account_line(account_id, vals, level, parent_id):
        line = {
            'id': "account-%s" % account_id,
            'name': "%s %s" % (vals['code'], vals['name']),
            'level': level,
            'columns': [
                {'expression_label': k, 'value': round(vals[k], 2)}
                for k in ('opening_debit', 'opening_credit',
                          'period_debit', 'period_credit',
                          'closing_debit', 'closing_credit')
            ],
            'unfoldable': False,
            'meta': {
                'account_id': account_id,
                'account_code': vals['code'],
            },
        }
        if parent_id:
            line['parent_id'] = parent_id
        return line
