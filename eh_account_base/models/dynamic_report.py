# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
eh.account.dynamic.report: the orchestrator model.

One record per concrete report (Trial Balance, P&L, Balance Sheet, ...).
The handler_model field references the AbstractModel that knows how to
compute that report. The render() method:

1. Computes the cache key from the options dict.
2. Looks up a prior successful execution with the same key. If the move
   version counter is unchanged since that execution, the cached payload
   is fresh and is returned directly.
3. On cache miss, instantiates the handler, runs compute(), persists the
   payload on a fresh execution row, and returns it.

Both paths return the same shape so callers cannot tell hit from miss
unless they inspect the from_cache flag.
"""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.eh_account_base.tools.payload_codec import (
    compress_payload, decompress_payload,
)
from odoo.addons.eh_account_base.tools.xlsx_writer import XlsxReportWriter

_logger = logging.getLogger(__name__)


class EhAccountDynamicReport(models.Model):
    _name = 'eh.account.dynamic.report'
    _description = "Dynamic accounting report"
    _order = 'sequence, name'

    code = fields.Char(required=True, copy=False, index=True)
    name = fields.Char(required=True, translate=True)
    handler_model = fields.Char(
        required=True,
        help="Odoo abstract model name implementing the report handler.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)

    _unique_code = models.Constraint(
        'unique(code)',
        'Report code must be unique.',
    )

    @api.constrains('handler_model')
    def _check_handler_model(self):
        for rec in self:
            if not rec.handler_model:
                raise ValidationError(_(
                    "Handler model is required for report %(code)r.",
                    code=rec.code,
                ))
            if rec.handler_model not in self.env.registry.models:
                raise ValidationError(_(
                    "Unknown handler model %(model)r for report %(code)r. "
                    "Did you forget to install the addon that provides "
                    "the handler?",
                    model=rec.handler_model,
                    code=rec.code,
                ))

    @api.model
    def get_by_code(self, code):
        report = self.search([('code', '=', code)], limit=1)
        if not report:
            raise UserError(_("Unknown report code: %s") % code)
        return report

    def get_default_options(self):
        self.ensure_one()
        return self.env[self.handler_model].build_default_options()

    def render(self, options, result_format='json', use_cache=True):
        """Run the report. Returns the same shape on hit and miss.

        Result dict keys:

        * columns, lines, totals, generated_at: from handler.compute().
        * execution_id: id of the eh.account.report.execution row.
        * from_cache: True when served from a prior execution payload.

        On error, the execution row is marked 'error' with the exception
        message, and the exception is re raised so the caller can surface it.
        """
        self.ensure_one()
        Execution = self.env['eh.account.report.execution']

        company_ids = (
            options.get('company_ids')
            or list(self.env.context.get(
                'allowed_company_ids', [self.env.company.id],
            ))
        )

        canonical = Execution._canonicalise_options(options)
        options_hash = Execution._hash_string(
            json.dumps(canonical, sort_keys=True, default=str)
        )

        if use_cache:
            cached = Execution.find_cached(
                self.code, options_hash, company_ids,
            )
            if cached and cached.result_payload:
                payload = decompress_payload(cached.result_payload)
                if payload is not None:
                    # Cache hit still gets its own audit row. The
                    # compliance promise is "every render is recorded";
                    # serving from cache without a row would lose every
                    # render after the first. The new row points at the
                    # cached execution via served_from_execution_id, so
                    # forensic replay can trace back to the source
                    # without storing duplicate payload bytes.
                    audit = Execution.start_execution(
                        report_code=self.code,
                        name=self.name,
                        options=options,
                        company_ids=company_ids,
                        result_format=result_format,
                    )
                    audit.complete_execution(
                        row_count=len(payload.get('lines', [])),
                        result_hash=cached.result_hash or False,
                    )
                    audit.write({'served_from_execution_id': cached.id})
                    _logger.info(
                        "Report %s cache HIT served_by=%s source=%s",
                        self.code, audit.id, cached.id,
                    )
                    payload['execution_id'] = audit.id
                    payload['from_cache'] = True
                    return payload

        execution = Execution.start_execution(
            report_code=self.code,
            name=self.name,
            options=options,
            company_ids=company_ids,
            result_format=result_format,
        )

        try:
            # Pass the report code via context so generic handlers (like
            # the custom report builder) can resolve which definition to
            # interpret without polluting the options dict.
            handler = self.env[self.handler_model].with_context(
                eh_report_code=self.code,
            )
            payload = handler.compute(options)
            # Attach currency info to every payload so the OWL viewer and
            # the XLSX writer can render amounts with the right symbol /
            # decimal places without each handler having to remember.
            if 'currency' not in payload:
                payload['currency'] = handler.resolve_currency_info(options)
            row_count = len(payload.get('lines', []))
            compressed = compress_payload(payload)
            execution.complete_execution(
                row_count=row_count,
                result_payload=compressed,
            )
            payload['execution_id'] = execution.id
            payload['from_cache'] = False
            return payload
        except Exception as exc:
            execution.fail_execution(str(exc))
            raise

    def render_xlsx(self, options, use_cache=True):
        """Render the report and return XLSX bytes.

        Equivalent to render() followed by passing the JSON payload to the
        XLSX writer. Cache hits short circuit recomputation, the writer
        runs against the cached payload directly.
        """
        self.ensure_one()
        payload = self.render(options, use_cache=use_cache)
        writer = XlsxReportWriter(report_name=self.name)
        return writer.write_payload(payload)

    def export_xlsx_attachment(self, options):
        """Render to XLSX, persist as ir.attachment, and return a download
        action.

        The OWL viewer calls this from the Export to Excel button. It exists
        because passing raw bytes through OWL's RPC layer is awkward; an
        attachment plus an act_url action is the conventional Odoo path.
        """
        import base64
        self.ensure_one()
        content = self.render_xlsx(options)
        date_block = options.get('date') or {}
        filename = "%s_%s_to_%s.xlsx" % (
            self.code,
            date_block.get('date_from') or '',
            date_block.get('date_to') or '',
        )
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content),
            'mimetype': (
                'application/vnd.openxmlformats-officedocument'
                '.spreadsheetml.sheet'
            ),
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'download',
        }

    def get_drilldown_for_line(self, options, line_id):
        """Return the handler's drill down action for a given line id.

        Thin RPC wrapper around the handler's get_drilldown_action so the
        OWL viewer can invoke it without holding a handler reference.
        Returns None when the line has no drill down (the OWL viewer
        treats falsy responses as a no op click).
        """
        self.ensure_one()
        handler = self.env[self.handler_model]
        return handler.get_drilldown_action(options, line_id)
