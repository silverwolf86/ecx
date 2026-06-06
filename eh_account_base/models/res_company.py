# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
res.company extension: per company move version counter.

The reporting cache uses (company_id, eh_move_version) as a freshness signal.
Every account.move state transition bumps this counter atomically. When a
cache lookup sees a different counter than the one stored at execution time,
the cached result is stale and recomputation runs.
"""

from odoo import fields, models
from odoo.tools import SQL


class ResCompany(models.Model):
    _inherit = 'res.company'

    eh_move_version = fields.Integer(
        string="Move Version Counter",
        default=0,
        copy=False,
        readonly=True,
        help=(
            "Internal counter incremented on every account.move state change. "
            "Used by the ERP Heritage reporting cache to detect staleness. "
            "Do not edit manually."
        ),
    )

    # ------------------------------------------------------------------
    # Settings persisted on the company so they survive across sessions.
    # The corresponding res.config.settings fields mirror these via
    # related/readonly=False so the operator edits them on the
    # standard Settings page.
    # ------------------------------------------------------------------

    # Reporting engine
    eh_gl_row_limit = fields.Integer(
        string="GL Row Limit",
        default=10000,
        help="Maximum row materialisation cap for row-driven reports.",
    )
    eh_dashboard_lookback_days = fields.Integer(
        string="Dashboard Lookback (days)",
        default=180,
        help="History window scanned by the financial dashboard tiles.",
    )

    # Reports Pro: forecasting defaults
    eh_forecast_default_horizon = fields.Integer(
        string="Default Forecast Horizon (months)",
        default=12,
    )
    eh_forecast_default_history_months = fields.Integer(
        string="Default Forecast History (months)",
        default=24,
    )

    # Assets and leases
    eh_asset_default_useful_life_months = fields.Integer(
        string="Default Asset Useful Life (months)",
        default=60,
    )
    eh_lease_default_term_months = fields.Integer(
        string="Default Lease Term (months)",
        default=36,
    )

    # Collections
    eh_collections_grace_days = fields.Integer(
        string="Collections Grace Days",
        default=14,
    )

    # AP Automation: parser defaults
    eh_ap_invoice_ref_regex = fields.Char(
        string="AP Invoice Ref Regex",
        default=r'(?im)Invoice[:#\s]+([A-Z0-9\-]+)',
    )
    eh_ap_total_regex = fields.Char(
        string="AP Total Amount Regex",
        default=r'(?im)Total[:\s]+([0-9][0-9,\.]*)',
    )

    # SEPA Direct Debit
    eh_sepa_dd_default_instrument = fields.Selection(
        [('CORE', "CORE (consumer)"),
         ('B2B', "B2B (business-to-business)"),
         ('COR1', "COR1 (one-day legacy)")],
        string="Default SEPA DD Local Instrument",
        default='CORE',
    )

    # Approval workflow
    eh_approval_material_change_pct = fields.Float(
        string="Approval Material Change %",
        default=10.0,
        help=(
            "If a request amount changes by more than this percentage "
            "after first approval, the workflow re-approves from step zero."
        ),
    )

    def _eh_bump_move_version(self, company_ids):
        """Atomically increment the counter for the given companies.

        Uses a direct SQL UPDATE so concurrent posts cannot race the
        counter out of sequence. Caller passes an iterable of company
        ids (not records) so the bump can fire from contexts where
        browsing the company would be unnecessary overhead. The cache
        is invalidated only on the affected company rows, not on every
        company in the registry.
        """
        ids = tuple(int(c) for c in company_ids)
        if not ids:
            return
        self.env.cr.execute(SQL(
            "UPDATE res_company SET eh_move_version = eh_move_version + 1 "
            "WHERE id IN %s",
            ids,
        ))
        self.env['res.company'].browse(ids).invalidate_recordset(
            ['eh_move_version'],
        )
