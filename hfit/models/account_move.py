
from odoo.exceptions import UserError
from odoo import models, fields, api
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

from dateutil import relativedelta
import math

def round_half_down(n, decimals=0):
    multiplier = 10**decimals
    return math.ceil(n * multiplier - 0.5) / multiplier

class AccountMove(models.Model):
    _inherit = 'account.move'
    
    cc_group_id = fields.Many2one(comodel_name='subscription.group', string='Grupo')
    brand_id = fields.Many2one(comodel_name='credit.card.brand', string='Marca Tarjeta')
    
    cobrado = fields.Boolean(string='Cobrado', default=False)
    fecha_cobro = fields.Date(string='Fecha Cobro',)

    enviado_contifico = fields.Boolean(string='Enviado a Contifico', default=False)
    numero_contifico = fields.Char(string='Numero Contifico', default=False, tracking=True)
    error_api = fields.Char(string='Error API', default=False)

    branch_id = fields.Many2one('res.branch', string='Sucursal')

    estado_cobro = fields.Selection([
        ('pendiente', 'Pendiente'),
        ('exito', 'Éxito'),
        ('fallido', 'Fallido'),
        ('transito', 'Transito'),
    ], string='Estado de Cobro', default='pendiente', tracking=True)
    intentos = fields.Integer(string='Intentos de Cobro', default=0)
    descripcion_cobro = fields.Char(string='Descripción Cobro', tracking=True)
    
    def action_post(self):
        print("ENTRO A ACTION POST OVERRIDE")

        transito_moves = self.filtered(lambda m: m.estado_cobro == 'transito')
        if transito_moves:
            names = ', '.join(filter(None, transito_moves.mapped('name')))
            msg = "No se pueden publicar ni cobrar las facturas en estado 'Transito de Tarjeta'."
            if names:
                msg = "%s Factura(s): %s" % (msg, names)
            raise UserError(msg)

        return super(AccountMove, self).action_post()


    def _l10n_ec_get_invoice_additional_info(self):
        return {
            "E-mail": self.partner_id.email or '',
            'Socio': self.partner_shipping_id.name or '',
        }
