# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class EcxAtsReport(models.Model):
    _name = 'ecx.ats.report'
    _inherit = ['ecx.ats.report.handler']
    _description = 'Ecuadorian ATS Report'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company,
    )
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)
    ignore_errors = fields.Boolean(
        string='Ignore Errors',
        help='Generate the ATS XML file even if missing or incorrect data was detected.',
    )
    error_message = fields.Text(string='Detected Errors', readonly=True)
    xml_filename = fields.Char(readonly=True)
    xml_file = fields.Binary(string='ATS XML File', readonly=True, attachment=True)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for report in self:
            if report.date_start > report.date_end:
                raise ValidationError(_('The start date must be before or equal to the end date.'))

    def action_generate_ats(self):
        self.ensure_one()
        if self.company_id.account_fiscal_country_id.code != 'EC':
            raise ValidationError(_('This report is only available for Ecuadorian companies.'))

        handler = self.with_company(self.company_id)
        xml_str, errors = handler._generate_ats(self.date_start, self.date_end)

        if errors and not self.ignore_errors:
            self.error_message = '\n'.join(errors)
            error_msg = _(
                'While preparing the data for the ATS export, we noticed the following missing or incorrect data.'
            ) + '\n\n' + '\n'.join(errors)
            raise ValidationError(error_msg)

        self.error_message = '\n'.join(errors) if errors else False
        self.xml_filename = 'ATS-%s-%s.xml' % (self.company_id.vat or self.company_id.name, self.date_end.strftime('%Y%m'))
        self.xml_file = base64.b64encode(xml_str.encode())

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/xml_file/%s?download=true' % (self._name, self.id, self.xml_filename),
            'target': 'self',
        }
