# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Intermediate handler base for section based reports.

Profit and Loss, Balance Sheet, and other "sections of accounts" reports
share the same shape:

* One or more sections, each containing a header line, one line per
  contributing account, and a section total.
* Per account aggregation comes from a single SQL pass per section,
  composed via MoveLineQuery.
* Optional aggregate scalars (Current Year Earnings on a Balance Sheet,
  for example) come from a smaller SQL pass with no group by.

Concrete handlers _inherit this model and call the helpers; they decide
which sections to render, how the totals roll up, and which line ids to
issue. Trial Balance and General Ledger do NOT inherit this base because
their layout differs.
"""

from datetime import timedelta

from odoo import _, api, models
from odoo.tools import SQL

from odoo.addons.eh_account_base.tools.sql_builder import MoveLineQuery


class EhAccountDynamicReportSectionedHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.sectioned'
    _inherit = 'eh.account.dynamic.report.handler'
    _description = "Base for section based dynamic report handlers"

    # ---- column layout ----
    #
    # Default labels are resolved with _() inside each method so they pick
    # up the active language at call time. Function-default expressions are
    # evaluated once at import time, so a literal default of "Description"
    # would freeze the English string. None signals "use the translated
    # default", and callers can still override with their own string.

    @api.model
    def _build_two_column_layout(self, label_name=None, amount_name=None):
        """Return the standard two column layout: label on the left,
        monetary amount on the right. Most section based reports use this.
        """
        return [
            {'expression_label': 'account',
             'name': label_name if label_name is not None else _("Description"),
             'figure_type': 'string'},
            {'expression_label': 'amount',
             'name': amount_name if amount_name is not None else _("Amount"),
             'figure_type': 'monetary'},
        ]

    @api.model
    def _build_comparative_column_layout(
        self, label_name=None, current_label=None,
        prior_label=None, variance_label=None,
        variance_pct_label=None,
    ):
        """Return the comparative four-column layout: label + current
        amount + prior amount + variance + variance %. Used when
        options['comparison'] is set.
        """
        return [
            {'expression_label': 'account',
             'name': label_name if label_name is not None else _("Description"),
             'figure_type': 'string'},
            {'expression_label': 'amount',
             'name': current_label if current_label is not None else _("Current"),
             'figure_type': 'monetary'},
            {'expression_label': 'prior_amount',
             'name': prior_label if prior_label is not None else _("Prior"),
             'figure_type': 'monetary'},
            {'expression_label': 'variance',
             'name': variance_label if variance_label is not None else _("Variance"),
             'figure_type': 'monetary'},
            {'expression_label': 'variance_pct',
             'name': variance_pct_label if variance_pct_label is not None else _("Var %"),
             'figure_type': 'percentage'},
        ]

    # ---- comparison helpers ----

    @api.model
    def _resolve_comparison_dates(self, mode, date_from, date_to):
        """Return (prior_from, prior_to, label) for a given comparison mode.

        Modes supported:
        * 'previous_period' shifts the [date_from, date_to] window backward
          by exactly its length minus one day, so a January window compares
          against December.
        * 'previous_year' shifts both ends back by one calendar year. A
          leap-day input (Feb 29) is shifted to Feb 28 of the prior year.

        Returns (None, None, '') for any other mode (no comparison).
        """
        if mode == 'previous_period':
            length = (date_to - date_from).days + 1
            prior_to = date_from - timedelta(days=1)
            prior_from = prior_to - timedelta(days=length - 1)
            return prior_from, prior_to, _("Previous period")
        if mode == 'previous_year':
            try:
                prior_from = date_from.replace(year=date_from.year - 1)
            except ValueError:
                prior_from = date_from.replace(
                    year=date_from.year - 1, day=date_from.day - 1,
                )
            try:
                prior_to = date_to.replace(year=date_to.year - 1)
            except ValueError:
                prior_to = date_to.replace(
                    year=date_to.year - 1, day=date_to.day - 1,
                )
            return prior_from, prior_to, _("Same period last year")
        return None, None, ""

    @staticmethod
    def _safe_pct(prior, current):
        """Variance percentage that does not divide by zero. Returns the
        difference as a fraction (1.0 = 100%) so the figure_type 'percentage'
        renders it correctly. With a zero prior, returns 1.0 if the current
        is non-zero (full overrun) and 0.0 otherwise.
        """
        if prior:
            return (current - prior) / abs(prior)
        if current:
            return 1.0
        return 0.0

    @api.model
    def merge_comparative_lines(self, current_lines, prior_lines):
        """Merge two single-amount line lists into multi-column lines.

        Both inputs are line lists as produced by the section helpers
        below; matching is by line.id. The output extends each current
        line's `columns` with the prior-period amount, the variance, and
        the variance percentage. Lines that exist in only one of the
        inputs receive zero on the missing side.
        """
        prior_by_id = {l['id']: l for l in prior_lines}
        merged = []
        seen = set()
        for cur in current_lines:
            seen.add(cur['id'])
            cur_amount = self._line_first_value(cur)
            prior = prior_by_id.get(cur['id'])
            prior_amount = self._line_first_value(prior) if prior else 0.0
            variance = round((cur_amount or 0.0) - (prior_amount or 0.0), 2)
            new_line = dict(cur)
            new_line['columns'] = [
                {'expression_label': 'amount', 'value': cur_amount},
                {'expression_label': 'prior_amount', 'value': prior_amount},
                {'expression_label': 'variance', 'value': variance},
                {'expression_label': 'variance_pct',
                 'value': self._safe_pct(prior_amount, cur_amount)},
            ]
            merged.append(new_line)
        # Lines that exist only in the prior period: emit them with a
        # zero current amount so the user sees that the activity has
        # ceased.
        for prior_id, prior in prior_by_id.items():
            if prior_id in seen:
                continue
            prior_amount = self._line_first_value(prior)
            new_line = dict(prior)
            new_line['columns'] = [
                {'expression_label': 'amount', 'value': 0.0},
                {'expression_label': 'prior_amount', 'value': prior_amount},
                {'expression_label': 'variance', 'value': -prior_amount},
                {'expression_label': 'variance_pct', 'value': -1.0},
            ]
            merged.append(new_line)
        return merged

    @staticmethod
    def _line_first_value(line):
        if not line:
            return 0.0
        cols = line.get('columns') or []
        if not cols:
            return 0.0
        return cols[0].get('value') or 0.0

    # ---- query helpers ----

    @api.model
    def _fetch_grouped_account_totals(
        self, account_types=None, company_ids=None,
        date_from=None, date_to=None,
        posted_only=True, options=None, sign=1,
    ):
        """Run a per account aggregation and return a list of dicts.

        Each result dict has keys: account_id, account_code, account_name,
        amount. The amount is the sum of balance for the matching journal
        lines, multiplied by sign. Sign is +1 for naturally debit accounts
        (assets, expenses) and -1 for naturally credit accounts (income,
        liabilities, equity), so amounts always present as positive in the
        report.
        """
        options = options or {}
        company_ids = company_ids or [self.env.company.id]
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_date_range(date_from=date_from, date_to=date_to)
        if posted_only:
            query.where_posted_only()
        if account_types:
            query.where_account_types(account_types)
        self.apply_common_filters(query, options)

        query.select_field('account_id')
        query.select_account_field('code', alias='account_code')
        query.select_account_field('name', alias='account_name')
        query.select(SQL("SUM(aml.balance)"), 'balance')
        query.group_by(
            SQL("aml.account_id"),
            SQL("(acc.code_store ->> aml.company_id::text)"),
            query._translated_account_name_sql(),
        )
        query.order_by_account_field('code', 'ASC')

        rows = query.execute()
        return [
            {
                'account_id': r['account_id'],
                'account_code': r['account_code'],
                'account_name': r['account_name'],
                'amount': float(r['balance'] or 0.0) * sign,
            }
            for r in rows
        ]

    @api.model
    def _fetch_aggregate_balance(
        self, account_types=None, company_ids=None,
        date_from=None, date_to=None,
        posted_only=True, options=None, sign=1,
    ):
        """Return a scalar: sum of balance with the given filters, multiplied
        by sign. No group by. Useful for computed lines like Current Year
        Earnings on a Balance Sheet.
        """
        options = options or {}
        company_ids = company_ids or [self.env.company.id]
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_date_range(date_from=date_from, date_to=date_to)
        if posted_only:
            query.where_posted_only()
        if account_types:
            query.where_account_types(account_types)
        self.apply_common_filters(query, options)

        query.select(SQL("SUM(aml.balance)"), 'balance')
        rows = query.execute()
        if not rows:
            return 0.0
        return float(rows[0].get('balance') or 0.0) * sign

    # ---- line factories ----

    @api.model
    def _render_account_lines(self, rows, show_zero=False):
        """Convert grouped account totals into report line dicts."""
        lines = []
        for r in rows:
            amount = round(r['amount'], 2)
            if not show_zero and amount == 0.0:
                continue
            lines.append({
                'id': "account-%s" % r['account_id'],
                'name': "%s %s" % (r['account_code'], r['account_name']),
                'level': 1,
                'columns': [
                    {'expression_label': 'amount', 'value': amount},
                ],
                'unfoldable': False,
                'meta': {
                    'account_id': r['account_id'],
                    'account_code': r['account_code'],
                },
            })
        return lines

    @api.model
    def _render_account_lines_grouped(
        self, rows, section_id, show_zero=False,
        unfolded_ids=None,
    ):
        """Convert per-account totals into a hierarchical line list
        nested by account.group.

        Walks account.account.group_id and account.group.parent_id to
        build the full group path for each account. Emits one line per
        group ancestor (level >= 1, unfoldable) and one line per
        account (leaf) parented to the deepest group. Accounts without
        a group attach directly to the section header.

        :param rows: list of {account_id, account_code, account_name,
            amount} dicts as returned by _fetch_grouped_account_totals.
        :param section_id: id of the parent section (the section header
            is emitted by the caller via _section_header_line).
        :param show_zero: include groups / accounts with zero balance.
        :param unfolded_ids: set of line ids the caller has marked as
            unfolded; lines whose parent is folded are still emitted
            but the renderer hides them. Defaults to "all groups
            unfolded" so the report renders fully expanded on first
            load.

        Returns the nested line list (excluding the section header
        itself, which the caller emits separately).
        """
        if not rows:
            return []
        unfolded_ids = unfolded_ids if unfolded_ids is not None else set()
        Account = self.env['account.account'].sudo()
        accounts = Account.browse([r['account_id'] for r in rows])
        # Cache amount per account_id for O(1) lookup.
        amount_by_id = {r['account_id']: round(r['amount'], 2) for r in rows}
        code_by_id = {r['account_id']: r['account_code'] for r in rows}
        name_by_id = {r['account_id']: r['account_name'] for r in rows}

        # Resolve full group path per account: list of (group_id,
        # group_name, group_code) from root to leaf, or [] for
        # ungrouped accounts. account.group.parent_id is the upstream
        # field that gives us the parent chain.
        group_paths = {}
        Group = self.env['account.group'].sudo()
        for acc in accounts:
            chain = []
            grp = acc.group_id
            while grp:
                chain.append((grp.id, grp.display_name or grp.name, grp.code_prefix_start or ''))
                grp = grp.parent_id
            chain.reverse()
            group_paths[acc.id] = chain

        # Aggregate amounts up the group tree. group_totals keys are
        # (section_id, group_id_path_tuple) so we can sum every account
        # that lives at or below each ancestor group.
        group_totals = {}  # path_tuple -> total
        accounts_by_group = {}  # path_tuple -> list of account ids
        for acc_id in amount_by_id:
            path = group_paths[acc_id]
            cumulative = ()
            # Accumulate at every ancestor depth.
            for entry in path:
                cumulative = cumulative + (entry[0],)
                group_totals[cumulative] = (
                    group_totals.get(cumulative, 0.0) + amount_by_id[acc_id]
                )
            # Track which group is the immediate parent for ungrouped
            # accounts (path empty -> attach to section header directly).
            parent_path = tuple(e[0] for e in path)
            accounts_by_group.setdefault(parent_path, []).append(acc_id)

        # Pre-compute the line id we will emit for each (path) tuple
        # so children can reference parent ids consistently.
        def _line_id_for_path(path_tuple):
            if not path_tuple:
                return "section-%s-header" % section_id
            return "section-%s-group-%s" % (
                section_id,
                "_".join(str(g) for g in path_tuple),
            )

        # Emit lines depth-first: every group, then its accounts,
        # sorted so that children appear under the right ancestor.
        lines = []
        # Build a sorted set of group paths (every prefix).
        all_paths = set()
        for parent_path in accounts_by_group:
            cumulative = ()
            for g in parent_path:
                cumulative = cumulative + (g,)
                all_paths.add(cumulative)
        # Sort paths so parents render before children, and siblings
        # render in code-prefix order to match the chart-of-accounts.
        def _path_sort_key(p):
            # Look up the code_prefix_start for each leg of the path
            # so siblings sort by prefix; falls back to id.
            keys = []
            for gid in p:
                grp = Group.browse(gid)
                keys.append((grp.code_prefix_start or '', gid))
            return keys
        ordered_paths = sorted(all_paths, key=_path_sort_key)

        # For each path, emit the group header then any accounts that
        # live exactly at that path. Accounts without a group emit
        # before any group lines (they hang directly off the section
        # header) so the user sees ungrouped items at the top.
        ungrouped = accounts_by_group.get((), [])
        if ungrouped:
            ungrouped.sort(key=lambda aid: code_by_id.get(aid, ''))
            for aid in ungrouped:
                amt = amount_by_id[aid]
                if not show_zero and amt == 0.0:
                    continue
                lines.append({
                    'id': "account-%s" % aid,
                    'name': "%s %s" % (code_by_id[aid], name_by_id[aid]),
                    'level': 1,
                    'parent_id': "section-%s-header" % section_id,
                    'columns': [
                        {'expression_label': 'amount', 'value': amt},
                    ],
                    'unfoldable': False,
                    'meta': {
                        'account_id': aid,
                        'account_code': code_by_id[aid],
                    },
                })

        for path in ordered_paths:
            path_total = round(group_totals.get(path, 0.0), 2)
            if not show_zero and path_total == 0.0:
                continue
            grp = Group.browse(path[-1])
            depth = len(path)
            parent_path = path[:-1]
            parent_id = _line_id_for_path(parent_path)
            this_id = _line_id_for_path(path)
            unfolded = (
                not unfolded_ids
                or this_id in unfolded_ids
            )
            lines.append({
                'id': this_id,
                'name': "%s %s" % (
                    grp.code_prefix_start or '',
                    grp.display_name or grp.name or '',
                ),
                'level': depth,
                'parent_id': parent_id,
                'columns': [
                    {'expression_label': 'amount', 'value': path_total},
                ],
                'unfoldable': True,
                'unfolded': unfolded,
                'meta': {
                    'kind': 'account_group',
                    'group_id': grp.id,
                    'depth': depth,
                },
            })
            # Accounts whose parent path is exactly this path.
            for aid in sorted(
                accounts_by_group.get(path, []),
                key=lambda a: code_by_id.get(a, ''),
            ):
                amt = amount_by_id[aid]
                if not show_zero and amt == 0.0:
                    continue
                lines.append({
                    'id': "account-%s" % aid,
                    'name': "%s %s" % (code_by_id[aid], name_by_id[aid]),
                    'level': depth + 1,
                    'parent_id': this_id,
                    'columns': [
                        {'expression_label': 'amount', 'value': amt},
                    ],
                    'unfoldable': False,
                    'meta': {
                        'account_id': aid,
                        'account_code': code_by_id[aid],
                    },
                })
        return lines

    @api.model
    def _section_header_line(self, name, section_id):
        # Empty string instead of None for the value: keeps the cell
        # blank in the OWL renderer and the PDF/XLSX exporter, but is
        # also serialisable through XML-RPC (where None is rejected
        # unless allow_none=True is set on the Marshaller, which the
        # Odoo default Marshaller does not).
        return {
            'id': "section-%s-header" % section_id,
            'name': name,
            'level': 0,
            'columns': [{'expression_label': 'amount', 'value': ''}],
            'unfoldable': False,
            'meta': {'kind': 'section_header', 'section_id': section_id},
        }

    @api.model
    def _section_total_line(self, name, total, section_id):
        return {
            'id': "section-%s-total" % section_id,
            'name': name,
            'level': 0,
            'columns': [
                {'expression_label': 'amount', 'value': round(total, 2)},
            ],
            'unfoldable': False,
            'meta': {'kind': 'section_total', 'section_id': section_id},
        }

    @api.model
    def _computed_line(self, line_id, name, amount, kind='computed'):
        """Standalone computed line (Net Profit, Current Year Earnings,
        Balance Check, etc.). Sits at level 0 in bold.
        """
        return {
            'id': line_id,
            'name': name,
            'level': 0,
            'columns': [
                {'expression_label': 'amount', 'value': round(amount, 2)},
            ],
            'unfoldable': False,
            'meta': {'kind': kind},
        }
