# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
General Ledger handler.

The first line level report in the bundle. Unlike Trial Balance, P&L, and
Balance Sheet (which aggregate to one line per account), General Ledger
renders one line per journal item, grouped under each account, with an
opening balance, every entry in the period, and a running closing balance.

Two SQL passes:

1. Opening balances per account: SUM(balance) where date < date_from.
   Returns a dict {account_id: opening_amount}.
2. Per line entries within [date_from, date_to]: ordered by account code,
   then date, then aml.id. Includes journal code, move name, partner name,
   label, debit, credit, and per line balance.

Running balance is computed in Python: starts at the opening, increments
by debit minus credit for each entry. This keeps the SQL simple and avoids
window functions that some PostgreSQL configurations are slower at.

Drill down:

* account-N (account header line): opens the journal items list filtered
  to that account and date range. Inherits the base default.
* aml-X (entry line): opens the specific journal entry form. Overridden
  here.

Other line ids (account-N-opening, account-N-total) are not drillable.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.tools.translate import LazyTranslate

from odoo.addons.eh_account_base.tools.sql_builder import MoveLineQuery

_lt = LazyTranslate(__name__)


# Absolute ceiling on rows materialised in a single render. The JSON
# payload bloats past this scale and the OWL viewer struggles with
# virtual scrolling. The default soft cap lives on the company record
# (eh_gl_row_limit) and the operator changes it under
# Settings > Accounting > ERP Heritage Reporting > GL Row Limit.
# The right path past the ceiling is to narrow the date range or add
# account / partner filters.
_ABSOLUTE_ROW_LIMIT = 100_000


class EhGeneralLedgerHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.general_ledger'
    _inherit = 'eh.account.dynamic.report.handler'
    _description = "General Ledger report handler"

    REPORT_CODE = 'general_ledger'
    REPORT_NAME = _lt("General Ledger")

    @api.model
    def compute(self, options):
        date_from = self._extract_date(options, 'date_from')
        date_to = self._extract_date(options, 'date_to')
        company_ids = options.get('company_ids') or [self.env.company.id]
        posted_only = bool(options.get('posted_only', True))
        show_zero = bool(options.get('show_zero', False))

        opening_by_account = self._fetch_opening_balances(
            company_ids=company_ids, date_from=date_from,
            posted_only=posted_only, options=options,
        )
        entries = self._fetch_line_entries(
            company_ids=company_ids,
            date_from=date_from, date_to=date_to,
            posted_only=posted_only, options=options,
        )

        lines = self._build_lines(opening_by_account, entries, show_zero)

        return {
            'columns': self._build_columns(),
            'lines': lines,
            'totals': {},
            'generated_at': fields.Datetime.now().isoformat(),
            'meta': {
                'report_code': self.REPORT_CODE,
                'date_from': self._iso_date(date_from),
                'date_to': self._iso_date(date_to),
                'company_ids': sorted(int(c) for c in company_ids),
                'posted_only': posted_only,
                'show_zero': show_zero,
            },
        }

    @api.model
    def get_drilldown_action(self, options, line_id):
        """Override: aml-X opens the specific journal entry form. Other ids
        fall through to the base account drill down (account-N).
        """
        if line_id and line_id.startswith('aml-'):
            try:
                aml_id = int(line_id.split('-', 1)[1])
            except ValueError:
                return None
            aml = self.env['account.move.line'].browse(aml_id).exists()
            if not aml:
                return None
            return {
                'type': 'ir.actions.act_window',
                'name': _("Journal Entry"),
                'res_model': 'account.move',
                'res_id': aml.move_id.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
            }
        return super().get_drilldown_action(options, line_id)

    # ---- internal helpers ----

    def _build_columns(self):
        return [
            {'expression_label': 'description', 'name': _("Description"),
             'figure_type': 'string'},
            {'expression_label': 'date', 'name': _("Date"),
             'figure_type': 'string'},
            {'expression_label': 'journal', 'name': _("Journal"),
             'figure_type': 'string'},
            {'expression_label': 'move', 'name': _("Move"),
             'figure_type': 'string'},
            {'expression_label': 'partner', 'name': _("Partner"),
             'figure_type': 'string'},
            {'expression_label': 'label', 'name': _("Label"),
             'figure_type': 'string'},
            {'expression_label': 'debit', 'name': _("Debit"),
             'figure_type': 'monetary'},
            {'expression_label': 'credit', 'name': _("Credit"),
             'figure_type': 'monetary'},
            {'expression_label': 'balance', 'name': _("Balance"),
             'figure_type': 'monetary'},
        ]

    def _fetch_opening_balances(
        self, company_ids, date_from, posted_only, options,
    ):
        """Return a dict {account_id: opening_balance, ...} where opening is
        the sum of balance for all lines strictly before date_from.
        """
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_raw(SQL("aml.date < %s", date_from))
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)

        query.select_field('account_id')
        query.select(SQL("SUM(aml.balance)"), 'opening_balance')
        query.group_by(SQL("aml.account_id"))

        rows = query.execute()
        return {
            r['account_id']: float(r['opening_balance'] or 0.0)
            for r in rows
        }

    def _fetch_line_entries(
        self, company_ids, date_from, date_to, posted_only, options,
    ):
        """Return a list of per line dicts ordered by account code, date,
        aml.id, with all the columns the report needs.

        Row count is capped to keep the payload bounded. The cap is
        enforced in two layers: a count-only query first (cheap, uses
        the index) tells us whether we are about to materialise too
        much data, and the SQL LIMIT on the data query is the
        belt-and-braces protection. When the count exceeds the
        requested limit we raise a UserError pointing the user at
        narrowing filters; we do not silently truncate, because a
        truncated GL is a subtly wrong financial document.
        """
        row_limit = self._resolve_row_limit(options)
        # Count-only pre-flight: same filters, single SUM, cheap.
        count_query = self._base_query(
            company_ids=company_ids, date_from=date_from, date_to=date_to,
            posted_only=posted_only, options=options,
        )
        count_query.select(SQL("COUNT(aml.id)"), 'row_count')
        count_rows = count_query.execute()
        total_rows = int(count_rows[0]['row_count']) if count_rows else 0
        if total_rows > row_limit:
            raise UserError(_(
                "General Ledger would return %(total)s journal items, "
                "exceeding the cap of %(limit)s. Narrow the date range "
                "or add account / partner filters, or pass options."
                "row_limit up to %(ceiling)s for an explicit higher cap.",
                total=total_rows,
                limit=row_limit,
                ceiling=_ABSOLUTE_ROW_LIMIT,
            ))

        query = self._base_query(
            company_ids=company_ids, date_from=date_from, date_to=date_to,
            posted_only=posted_only, options=options,
        )
        query.select_field('id', alias='aml_id')
        query.select_field('account_id')
        query.select_field('partner_id')
        query.select_field('date')
        query.select_field('debit')
        query.select_field('credit')
        query.select_field('balance')
        query.select_field('name', alias='line_label')
        query.select_field('ref')
        query.select_account_field('code', alias='account_code')
        query.select_account_field('name', alias='account_name')
        query.join_journal()
        query.select(SQL("aj.code"), 'journal_code')
        query.join_partner()
        query.select(SQL("p.name"), 'partner_name')
        query.select(SQL("am.name"), 'move_name')

        query.order_by_account_field('code', 'ASC')
        query.order_by('date', 'ASC')
        query.order_by('id', 'ASC')
        query.limit(row_limit)

        return query.execute()

    def _base_query(
        self, company_ids, date_from, date_to, posted_only, options,
    ):
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_date_range(date_from=date_from, date_to=date_to)
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)
        return query

    @api.model
    def _resolve_row_limit(self, options):
        # Soft cap is the per-company setting; the absolute ceiling is a
        # hard constant the operator cannot override.
        soft_cap = self.env.company.eh_gl_row_limit or 10000
        requested = options.get('row_limit')
        if requested is None:
            return soft_cap
        try:
            requested = int(requested)
        except (TypeError, ValueError):
            return soft_cap
        if requested <= 0:
            return soft_cap
        return min(requested, _ABSOLUTE_ROW_LIMIT)

    def _build_lines(self, opening_by_account, entries, show_zero):
        """Compose the hierarchical line list.

        Account ordering: defined by the entry stream (which is ordered by
        account code). Accounts that have only an opening balance and no
        period entries are still rendered (sorted by account_id; their
        position is best effort since we do not have their codes from the
        opening query). show_zero forces accounts with neither activity nor
        opening to appear, but in practice the GL only knows about accounts
        that have at least one move line, so the flag is informational.
        """
        # Group entries by account, preserving order.
        entries_by_account = {}
        account_meta = {}
        for entry in entries:
            entries_by_account.setdefault(entry['account_id'], []).append(entry)
            account_meta.setdefault(entry['account_id'], {
                'code': entry['account_code'],
                'name': entry['account_name'],
            })

        # Accounts that have no entries but do have an opening balance still
        # deserve a header + initial balance + total. We do not have their
        # codes from the opening query alone; fetch lazily.
        accounts_with_opening_only = (
            set(opening_by_account.keys()) - set(entries_by_account.keys())
        )
        if accounts_with_opening_only:
            for acc in self.env['account.account'].browse(
                list(accounts_with_opening_only),
            ).sorted('code'):
                account_meta[acc.id] = {
                    'code': acc.code or '',
                    'name': acc.name or '',
                }

        # Build the account ordering: entries first (in their order), then
        # opening only accounts (sorted by code).
        ordered_account_ids = list(entries_by_account.keys())
        ordered_account_ids += sorted(
            accounts_with_opening_only,
            key=lambda i: account_meta[i]['code'],
        )

        lines = []
        for account_id in ordered_account_ids:
            opening = round(opening_by_account.get(account_id, 0.0), 2)
            account_entries = entries_by_account.get(account_id, [])
            meta = account_meta[account_id]

            if not show_zero and opening == 0.0 and not account_entries:
                continue

            lines.append(self._account_header_line(account_id, meta))
            lines.append(self._opening_line(account_id, opening))

            running = opening
            for entry in account_entries:
                debit = round(float(entry.get('debit') or 0.0), 2)
                credit = round(float(entry.get('credit') or 0.0), 2)
                running = round(running + debit - credit, 2)
                lines.append(self._entry_line(entry, debit, credit, running))

            lines.append(self._account_total_line(account_id, meta, running))
        return lines

    def _account_header_line(self, account_id, meta):
        return {
            'id': "account-%s" % account_id,
            'name': "%s %s" % (meta['code'], meta['name']),
            'level': 0,
            'columns': [
                {'expression_label': 'date', 'value': ''},
                {'expression_label': 'journal', 'value': ''},
                {'expression_label': 'move', 'value': ''},
                {'expression_label': 'partner', 'value': ''},
                {'expression_label': 'label', 'value': ''},
                {'expression_label': 'debit', 'value': ''},
                {'expression_label': 'credit', 'value': ''},
                {'expression_label': 'balance', 'value': ''},
            ],
            'unfoldable': False,
            'meta': {
                'kind': 'account_header',
                'account_id': account_id,
                'account_code': meta['code'],
            },
        }

    def _opening_line(self, account_id, opening):
        return {
            'id': "account-%s-opening" % account_id,
            'name': _("Initial Balance"),
            'level': 1,
            'columns': [
                {'expression_label': 'date', 'value': ''},
                {'expression_label': 'journal', 'value': ''},
                {'expression_label': 'move', 'value': ''},
                {'expression_label': 'partner', 'value': ''},
                {'expression_label': 'label', 'value': ''},
                {'expression_label': 'debit', 'value': ''},
                {'expression_label': 'credit', 'value': ''},
                {'expression_label': 'balance', 'value': opening},
            ],
            'unfoldable': False,
            'meta': {'kind': 'opening_balance', 'account_id': account_id},
        }

    def _entry_line(self, entry, debit, credit, running_balance):
        return {
            'id': "aml-%s" % entry['aml_id'],
            'name': entry.get('ref') or entry.get('line_label') or '',
            'level': 1,
            'columns': [
                {'expression_label': 'date',
                 'value': self._iso_date(entry['date']) if entry.get('date') else None},
                {'expression_label': 'journal',
                 'value': entry.get('journal_code') or ''},
                {'expression_label': 'move',
                 'value': entry.get('move_name') or ''},
                {'expression_label': 'partner',
                 'value': entry.get('partner_name') or ''},
                {'expression_label': 'label',
                 'value': entry.get('line_label') or ''},
                {'expression_label': 'debit', 'value': debit},
                {'expression_label': 'credit', 'value': credit},
                {'expression_label': 'balance', 'value': running_balance},
            ],
            'unfoldable': False,
            'meta': {
                'kind': 'aml',
                'aml_id': entry['aml_id'],
                'account_id': entry['account_id'],
            },
        }

    def _account_total_line(self, account_id, meta, closing):
        return {
            'id': "account-%s-total" % account_id,
            'name': _("Total %(code)s %(name)s") % {
                'code': meta['code'], 'name': meta['name'],
            },
            'level': 0,
            'columns': [
                {'expression_label': 'date', 'value': ''},
                {'expression_label': 'journal', 'value': ''},
                {'expression_label': 'move', 'value': ''},
                {'expression_label': 'partner', 'value': ''},
                {'expression_label': 'label', 'value': ''},
                {'expression_label': 'debit', 'value': ''},
                {'expression_label': 'credit', 'value': ''},
                {'expression_label': 'balance', 'value': closing},
            ],
            'unfoldable': False,
            'meta': {'kind': 'account_total', 'account_id': account_id},
        }
