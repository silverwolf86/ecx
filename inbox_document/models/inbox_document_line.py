from odoo import api, fields, models
from odoo.tools import float_is_zero


class InboxDocumentLine(models.Model):
    _name = 'inbox.document.xml.detail'
    _description = 'Línea del XML del documento de entrada'
    _rec_name = 'name'

    document_id = fields.Many2one(
        comodel_name='inbox.document',
        string='Documento de Entrada',
        required=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(related='document_id.company_id', store=True)
    name = fields.Char(string='Descripción')
    product_id = fields.Many2one(comodel_name='product.product', string='Producto')
    product_code = fields.Char(string='Código del Producto')
    quantity = fields.Float(string='Cantidad', digits='Product Unit of Measure')
    price_unit = fields.Float(string='Precio Unitario', digits='Product Price')
    discount_amount = fields.Float(
        string='Descuento (importe)',
        digits='Product Price',
        help='Importe de descuento tal como viene en el XML del SRI.',
    )
    discount = fields.Float(
        string='Descuento (%)',
        digits='Discount',
        compute='_compute_discount',
        store=True,
        help='Porcentaje de descuento, calculado sobre el subtotal bruto de la línea.',
    )
    tax_ids = fields.Many2many(comodel_name='account.tax', string='Impuestos')

    @api.depends('discount_amount', 'quantity', 'price_unit')
    def _compute_discount(self):
        for line in self:
            gross = line.quantity * line.price_unit
            if float_is_zero(gross, precision_rounding=0.01):
                line.discount = 0.0
            else:
                line.discount = (line.discount_amount / gross) * 100.0
