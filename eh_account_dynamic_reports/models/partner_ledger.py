# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Partner Ledger handler.

Mirrors the General Ledger structure but groups by partner instead of by
account. For each partner that has activity in the period (or an opening
balance from before), the report renders:

* A partner header line (level 0).
* An opening balance line (level 1) reflecting all lines strictly before
  date_from.
* One entry line (level 1) per journal item in the period, with date,
  journal code, move name, account label, line label, debit, credit, and
  running balance.
* A partner total line (level 0) showing the closing balance.

By default only journal items that have a partner_id are included. The
account_ids filter can narrow further (for example, to receivables only)
but the default scope intentionally includes any account with a partner
attached, so cash payments to partners and other partner referenced
movements show alongside receivable/payable activity.

Drill down:

* partner-N: opens the journal items list filtered to the partner and
  the active date range.
* aml-X: opens the specific journal entry form.
"""

from odoo import _, api, fields, models
from odoo.tools import SQL
from odoo.tools.translate import LazyTranslate

from odoo.addons.eh_account_base.tools.sql_builder import MoveLineQuery

_lt = LazyTranslate(__name__)


class EhPartnerLedgerHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler.partner_ledger'
    _inherit = 'eh.account.dynamic.report.handler'
    _description = "Partner Ledger report handler"

    REPORT_CODE = 'partner_ledger'
    REPORT_NAME = _lt("Partner Ledger")

    @api.model
    def compute(self, options):
        date_from = self._extract_date(options, 'date_from')
        date_to = self._extract_date(options, 'date_to')
        company_ids = options.get('company_ids') or [self.env.company.id]
        posted_only = bool(options.get('posted_only', True))
        show_zero = bool(options.get('show_zero', False))

        opening_by_partner = self._fetch_opening_balances(
            company_ids=company_ids, date_from=date_from,
            posted_only=posted_only, options=options,
        )
        entries = self._fetch_line_entries(
            company_ids=company_ids,
            date_from=date_from, date_to=date_to,
            posted_only=posted_only, options=options,
        )

        lines = self._build_lines(opening_by_partner, entries, show_zero)

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
        """aml-X opens the journal entry form. partner-N opens the journal
        items list filtered to that partner. Other ids return None.
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
        if line_id and line_id.startswith('partner-'):
            rest = line_id.split('-', 1)[1]
            if not rest.isdigit():
                return None
            partner_id = int(rest)
            try:
                date_from = self._extract_date(options, 'date_from')
                date_to = self._extract_date(options, 'date_to')
            except Exception:
                return None
            company_ids = options.get('company_ids') or [self.env.company.id]
            domain = [
                ('partner_id', '=', partner_id),
                ('company_id', 'in', list(company_ids)),
                ('date', '>=', self._iso_date(date_from)),
                ('date', '<=', self._iso_date(date_to)),
            ]
            if options.get('posted_only', True):
                domain.append(('parent_state', '=', 'posted'))
            return {
                'type': 'ir.actions.act_window',
                'name': _("Journal Items"),
                'res_model': 'account.move.line',
                'view_mode': 'list,form',
                'domain': domain,
            }
        return None

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
            {'expression_label': 'account', 'name': _("Account"),
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
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_raw(SQL("aml.date < %s", date_from))
        query.where_raw(SQL("aml.partner_id IS NOT NULL"))
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)

        query.select_field('partner_id')
        query.select(SQL("SUM(aml.balance)"), 'opening_balance')
        query.group_by(SQL("aml.partner_id"))

        rows = query.execute()
        return {
            r['partner_id']: float(r['opening_balance'] or 0.0)
            for r in rows
        }

    def _fetch_line_entries(
        self, company_ids, date_from, date_to, posted_only, options,
    ):
        query = MoveLineQuery(self.env, company_ids=company_ids)
        query.where_date_range(date_from=date_from, date_to=date_to)
        query.where_raw(SQL("aml.partner_id IS NOT NULL"))
        if posted_only:
            query.where_posted_only()
        self.apply_common_filters(query, options)

        query.select_field('id', alias='aml_id')
        query.select_field('partner_id')
        query.select_field('account_id')
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

        query.order_by(SQL("aml.partner_id"), 'ASC')
        query.order_by('date', 'ASC')
        query.order_by('id', 'ASC')

        return query.execute()

    def _build_lines(self, opening_by_partner, entries, show_zero):
        # Group entries by partner, preserving order.
        entries_by_partner = {}
        partner_meta = {}
        for entry in entries:
            entries_by_partner.setdefault(
                entry['partner_id'], [],
            ).append(entry)
            partner_meta.setdefault(entry['partner_id'], {
                'name': entry.get('partner_name') or '',
            })

        # Partners with opening only need their names fetched separately.
        opening_only_ids = (
            set(opening_by_partner.keys()) - set(entries_by_partner.keys())
        )
        if opening_only_ids:
            for partner in self.env['res.partner'].browse(
                list(opening_only_ids),
            ).sorted('display_name'):
                partner_meta[partner.id] = {
                    'name': partner.display_name or partner.name or '',
                }

        ordered_partner_ids = list(entries_by_partner.keys())
        ordered_partner_ids += sorted(
            opening_only_ids,
            key=lambda i: partner_meta[i]['name'],
        )

        lines = []
        for partner_id in ordered_partner_ids:
            opening = round(opening_by_partner.get(partner_id, 0.0), 2)
            partner_entries = entries_by_partner.get(partner_id, [])
            meta = partner_meta[partner_id]

            if not show_zero and opening == 0.0 and not partner_entries:
                continue

            lines.append(self._partner_header_line(partner_id, meta))
            lines.append(self._opening_line(partner_id, opening))

            running = opening
            for entry in partner_entries:
                debit = round(float(entry.get('debit') or 0.0), 2)
                credit = round(float(entry.get('credit') or 0.0), 2)
                running = round(running + debit - credit, 2)
                lines.append(self._entry_line(entry, debit, credit, running))

            lines.append(self._partner_total_line(partner_id, meta, running))
        return lines

    def _partner_header_line(self, partner_id, meta):
        return {
            'id': "partner-%s" % partner_id,
            'name': meta['name'] or "(no name)",
            'level': 0,
            'columns': [
                {'expression_label': 'date', 'value': ''},
                {'expression_label': 'journal', 'value': ''},
                {'expression_label': 'move', 'value': ''},
                {'expression_label': 'account', 'value': ''},
                {'expression_label': 'label', 'value': ''},
                {'expression_label': 'debit', 'value': ''},
                {'expression_label': 'credit', 'value': ''},
                {'expression_label': 'balance', 'value': ''},
            ],
            'unfoldable': False,
            'meta': {
                'kind': 'partner_header',
                'partner_id': partner_id,
            },
        }

    def _opening_line(self, partner_id, opening):
        return {
            'id': "partner-%s-opening" % partner_id,
            'name': _("Initial Balance"),
            'level': 1,
            'columns': [
                {'expression_label': 'date', 'value': ''},
                {'expression_label': 'journal', 'value': ''},
                {'expression_label': 'move', 'value': ''},
                {'expression_label': 'account', 'value': ''},
                {'expression_label': 'label', 'value': ''},
                {'expression_label': 'debit', 'value': ''},
                {'expression_label': 'credit', 'value': ''},
                {'expression_label': 'balance', 'value': opening},
            ],
            'unfoldable': False,
            'meta': {'kind': 'opening_balance', 'partner_id': partner_id},
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
                {'expression_label': 'account',
                 'value': "%s %s" % (
                     entry.get('account_code') or '',
                     entry.get('account_name') or '',
                 )},
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
                'partner_id': entry['partner_id'],
                'account_id': entry['account_id'],
            },
        }

    def _partner_total_line(self, partner_id, meta, closing):
        return {
            'id': "partner-%s-total" % partner_id,
            'name': _("Total %s") % (meta['name'] or _("(no name)")),
            'level': 0,
            'columns': [
                {'expression_label': 'date', 'value': ''},
                {'expression_label': 'journal', 'value': ''},
                {'expression_label': 'move', 'value': ''},
                {'expression_label': 'account', 'value': ''},
                {'expression_label': 'label', 'value': ''},
                {'expression_label': 'debit', 'value': ''},
                {'expression_label': 'credit', 'value': ''},
                {'expression_label': 'balance', 'value': closing},
            ],
            'unfoldable': False,
            'meta': {'kind': 'partner_total', 'partner_id': partner_id},
        }
