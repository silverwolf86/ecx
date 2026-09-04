from odoo import models, fields

class SaleReport(models.Model):
    _inherit = "sale.report"

    branch_id = fields.Many2one(
        'res.branch',
        string='Sucursal',
        readonly=True
    )

    def _select_additional_fields(self):
        res = super()._select_additional_fields()
        res['branch_id'] = 's.branch_id'    
        return res

    def _group_by_sale(self):
        return super()._group_by_sale() + ",\n            s.branch_id"
