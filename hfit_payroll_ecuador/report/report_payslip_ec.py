from datetime import datetime, time

import babel.dates

from odoo import api, fields, models


class ReportPayslipEc(models.AbstractModel):
    _name = 'report.hfit_payroll_ecuador.report_payslip_ec'
    _description = 'Rol de pago individual'

    # Categorías que no son ingreso ni egreso para el empleado.
    EXCLUDED_CATEGORIES = ('NET', 'GROSS', 'PROV', 'COMP')
    INCOME_CATEGORIES = {'BASIC', 'ALW'}

    @api.model
    def _category_codes(self, category):
        """Códigos de la categoría y de todas sus categorías padre."""
        codes = set()
        while category:
            codes.add(category.code)
            category = category.parent_id
        return codes

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['hr.payslip'].browse(docids)
        values = {}
        for slip in docs:
            lines = slip.line_ids.filtered(
                lambda l: l.category_id.code not in self.EXCLUDED_CATEGORIES)
            # Ingresos: categorías BASIC y ALW (o hijas de ellas), aunque el
            # monto sea 0. Egresos: el resto con monto distinto de 0.
            ingresos = lines.filtered(
                lambda l: self._category_codes(l.category_id) & self.INCOME_CATEGORIES
                or l.total > 0)
            egresos = (lines - ingresos).filtered('total')
            month = babel.dates.format_date(
                datetime.combine(fields.Date.to_date(slip.date_from), time.min),
                format='MMMM', locale='es')
            values[slip.id] = {
                'ingresos': ingresos,
                'egresos': egresos,
                'total_ingresos': sum(ingresos.mapped('total')),
                'total_egresos': sum(egresos.mapped('total')),
                'month': month.upper(),
            }
        return {
            'doc_ids': docids,
            'doc_model': 'hr.payslip',
            'docs': docs,
            'values': values,
            'now': fields.Datetime.context_timestamp(self, fields.Datetime.now()),
            'user_name': self.env.user.name,
        }
