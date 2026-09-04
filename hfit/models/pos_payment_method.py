from odoo import api, fields, models


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_payroll_discount = fields.Boolean(
        string='Descuento por Rol',
        default=False,
        help='Indica que este método de pago corresponde a un descuento por rol de pagos. '
             'Requiere que el cliente tenga un empleado asociado.',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        return fields_list + ['is_payroll_discount']
