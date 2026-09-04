from odoo import models, fields, api
import requests
from datetime import datetime, timedelta
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup, escape
import re

import logging

_logger = logging.getLogger(__name__)

class SaleOrderCcHistory(models.Model):
    _name = 'sale.order.cc.history'
    _description = 'Historial de Cambios de Tarjeta de Crédito en Pedidos'
    _order = 'change_date desc'

    order_id = fields.Many2one(
        'sale.order', 
        string="Pedido de Venta", 
        ondelete='cascade', 
        required=True,
        index=True
    )
    user_id = fields.Many2one('res.users', string="Modificado por", readonly=True)
    change_date = fields.Datetime(string="Fecha del Cambio", readonly=True, default=fields.Datetime.now)
    new_value_masked = fields.Char(string="Nuevo Valor (Terminación)", readonly=True)


class CreditCardBrand(models.Model):
    _name = 'credit.card.brand'
    _description = 'Marca Tarjeta'
    _rec_name = "name"

    name = fields.Char(string='Marca')
    code = fields.Char(string='codigo')
    sequence_header_id = fields.Many2one(comodel_name='ir.sequence', string='Secuencia Header')
    sequence_detail_id = fields.Many2one(comodel_name='ir.sequence', string='Secuencia Detalle')
    