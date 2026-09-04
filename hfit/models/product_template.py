from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    virtuagym_membership_id = fields.Integer(
        string='Virtuagym Membership ID',
        help='ID de la definición de membresía en Virtuagym que se asigna al socio '
             'al confirmar una orden de venta con este producto.',
    )
