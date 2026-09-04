from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    faceid_access_duration_value = fields.Integer(
        string='Duración de Acceso FaceID',
        help='Valor numérico para la duración del acceso cuando no es suscripción (ej: 1, 30, 6)'
    )
    faceid_access_duration_unit = fields.Selection([
        ('days', 'Días'),
        ('weeks', 'Semanas'),
        ('months', 'Meses'),
        ('years', 'Años')
    ], string='Unidad de Duración FaceID', default='months',
       help='Unidad de tiempo para la duración del acceso no recurrente.')
