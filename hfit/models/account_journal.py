
from odoo.exceptions import UserError
from odoo import models, fields, api
import logging
import requests
from datetime import datetime

_logger = logging.getLogger(__name__)



class AccountJournal(models.Model):
    _inherit = 'account.journal'
    
    branch_id = fields.Many2one('res.branch', string='Sucursal')