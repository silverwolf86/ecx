# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
Abstract base for dynamic report handlers.

Concrete handlers _inherit this model and override compute(). The
orchestrator (eh.account.dynamic.report) instantiates the handler by model
name and calls compute() with the options dict.

Why an Odoo AbstractModel and not a plain Python class:

* Localizations and add ons can extend a handler with _inherit, override
  compute(), and add new lines or columns without touching the base addon.
* Discovery through self.env[handler_model] is one line and consistent with
  the rest of the framework.
* Inheritance composition (multiple addons stacking on the same handler)
  works out of the box.

Shared helpers live here so concrete handlers stay small and focused on
report specific math:

* _extract_date(options, key): pulls and parses a date from options['date'].
* _iso_date(value): renders a date or string back to ISO format.
* get_drilldown_action(options, line_id): default account drill down to
  filtered journal items. Concrete handlers override only when their
  line_id scheme differs.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EhAccountDynamicReportHandler(models.AbstractModel):
    _name = 'eh.account.dynamic.report.handler'
    _description = "Base for ERP Heritage dynamic report handlers"

    REPORT_CODE = ''
    REPORT_NAME = ""

    @api.model
    def build_default_options(self):
        """Return the default options dict for this report.

        Subclasses may override to add report specific defaults. Always call
        super() and merge.
        """
        today = fields.Date.today()
        first_of_month = today.replace(day=1)
        return {
            'date': {
                'mode': 'range',
                'date_from': first_of_month.isoformat(),
                'date_to': today.isoformat(),
            },
            'company_ids': list(
                self.env.context.get(
                    'allowed_company_ids',
                    [self.env.company.id],
                )
            ),
            'journal_ids': [],
            'partner_ids': [],
            'account_ids': [],
            'analytic_account_ids': [],
            'analytic_plan_ids': [],
            'unfolded_lines': [],
            'show_zero': False,
            'posted_only': True,
            'comparative': None,
            'currency_display': 'symbol',
        }

    @api.model
    def compute(self, options):
        """Compute the report data.

        Returns a dict with keys:

        * columns: list of dicts with name, expression_label, figure_type
          (string, monetary, percentage, integer, float, date, boolean).
        * lines: list of dicts with id, name, level, columns (list of value
          dicts), unfoldable (bool), parent_id (optional), meta (optional).
        * totals: optional dict mapping expression_label to summary value.
        * generated_at: ISO datetime string.
        """
        raise NotImplementedError(
            "Concrete handlers must override compute(options)."
        )

    @api.model
    def resolve_currency_info(self, options):
        """Resolve the currency block to attach to a report payload.

        When a single company is in scope, the company's currency is the
        report currency; when multiple companies share the same currency,
        the same applies. When the scope spans companies with different
        currencies the report cannot be expressed in a single currency
        without conversion, so we mark the payload as multi_currency and
        leave amount formatting to use no symbol.

        Returns a dict with keys: id, name, symbol, position, decimal_places,
        multi_currency.
        """
        company_ids = (
            options.get('company_ids')
            or list(self.env.context.get(
                'allowed_company_ids', [self.env.company.id],
            ))
        )
        companies = self.env['res.company'].sudo().browse(company_ids)
        currencies = companies.mapped('currency_id')
        unique = currencies.filtered(lambda c: c)
        if len(unique) <= 1 and unique:
            currency = unique[:1]
            return {
                'id': currency.id,
                'name': currency.name,
                'symbol': currency.symbol,
                'position': currency.position,
                'decimal_places': currency.decimal_places,
                'multi_currency': False,
            }
        return {
            'id': False,
            'name': '',
            'symbol': '',
            'position': 'after',
            'decimal_places': 2,
            'multi_currency': True,
        }

    @api.model
    def apply_common_filters(self, query, options):
        """Apply the standard option filters (journal_ids, partner_ids,
        account_ids, analytic_account_ids, analytic_plan_ids) to a
        MoveLineQuery. Centralised so adding a new dimension lands in one
        place instead of every concrete handler.
        """
        if options.get('journal_ids'):
            query.where_journals(options['journal_ids'])
        if options.get('partner_ids'):
            query.where_partners(options['partner_ids'])
        if options.get('account_ids'):
            query.where_accounts(options['account_ids'])
        if options.get('analytic_account_ids'):
            query.where_analytic_accounts(options['analytic_account_ids'])
        if options.get('analytic_plan_ids'):
            query.where_analytic_plans(options['analytic_plan_ids'])
        return query

    @api.model
    def get_drilldown_action(self, options, line_id):
        """Default drill down: open filtered journal items when line_id is
        of the form 'account-N'. Concrete handlers override only when their
        line_id scheme differs or when they want to disable drill down.
        """
        if not line_id or not isinstance(line_id, str):
            return None
        if not line_id.startswith('account-'):
            return None
        try:
            account_id = int(line_id.split('-', 1)[1])
        except ValueError:
            return None
        try:
            date_from = self._extract_date(options, 'date_from')
            date_to = self._extract_date(options, 'date_to')
        except UserError:
            return None
        company_ids = options.get('company_ids') or [self.env.company.id]
        domain = [
            ('account_id', '=', account_id),
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
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
            'context': {'search_default_group_move': 1},
        }

    # ---- shared helpers used by concrete handlers ----

    def _extract_date(self, options, key):
        """Pull options['date'][key] and return a Python date.

        Raises UserError if the date is missing. The error message includes
        the report's display name so the user can identify which report
        rejected the input.
        """
        date_block = options.get('date') or {}
        value = date_block.get(key)
        if not value:
            raise UserError(_(
                "%(report)s requires options['date'][%(key)s].",
                report=self.REPORT_NAME or "Report",
                key=repr(key),
            ))
        if isinstance(value, str):
            return fields.Date.from_string(value)
        return value

    @staticmethod
    def _iso_date(value):
        """Render a date or compatible value back to ISO format."""
        return value.isoformat() if hasattr(value, 'isoformat') else str(value)
