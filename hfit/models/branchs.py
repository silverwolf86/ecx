from odoo import models, fields, api


class ResCompany(models.Model):
    _inherit = 'res.company'
    
    virtuagym_api_url = fields.Char('Api URL')
    datafast_code = fields.Char('Datafast Code', required=False)


class Branch(models.Model):
    _name = 'res.branch'

    name = fields.Char(string='Nombre Sucursal', required=True)
    code = fields.Char(string='Codigo Sucursal', required=False)
    active = fields.Boolean(string='Activo', default=True) 

    virtuagym_club_id = fields.Char(string='Virtuagym Club ID', required=False)
    virtuagym_club_secret = fields.Char(string='Virtuagym Club Secret', required=False)
    virtuagym_api_key = fields.Char(string='Virtuagym API Key', required=False)
    virtuagym_salesperson_id = fields.Integer(
        string='Virtuagym Salesperson ID',
        required=False,
        help='ID del vendedor en Virtuagym usado al crear membresías (membership instances) '
             'para los socios de esta sucursal.',
    )

    collect_datacard_code = fields.Char(string='Codigo para recolectar datacard', required=False)

    face_id_url = fields.Char(string='Face ID URL', required=False)
    face_id_user = fields.Char(string='Face ID Usuario', required=False)
    face_id_password = fields.Char(string='Face ID Password', required=False)