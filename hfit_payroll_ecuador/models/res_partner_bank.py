from odoo import fields, models


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    account_type = fields.Selection(
        [('AHO', 'Ahorros'), ('CTE', 'Corriente')],
        string='Tipo de Cuenta',
        help='Tipo de cuenta bancaria usado en el archivo de pagos al banco.',
    )
