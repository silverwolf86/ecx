from odoo import models, fields, api

class GymFaceidLog(models.Model):
    _name = 'gym.faceid.log'
    _description = 'FaceID ISAPI Synchronization Log'
    _order = 'create_date desc'

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True, index=True, default=lambda self: 'New Log')
    
    action = fields.Selection([
        ('search', 'Search UserInfo'),
        ('record', 'Create UserInfo'),
        ('modify', 'Modify UserInfo'),
        ('delete', 'Delete UserInfo')
    ], string='Acción ISAPI', required=True, readonly=True)

    status_code = fields.Char(string='Código de Estado', readonly=True)
    response_text = fields.Text(string='Respuesta (Truncada)', readonly=True)
    payload = fields.Text(string='Payload Enviado', readonly=True)

    branch_id = fields.Many2one('res.branch', string='Sucursal', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Orden de Venta / Suscripción', readonly=True)

    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('ok', 'Éxito'),
        ('error', 'Error')
    ], string='Estado de Sincronización', default='pending', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'New Log':
                action_str = dict(self._fields['action'].selection).get(vals.get('action'), 'Unknown')
                vals['name'] = f"FaceID - {action_str}"
        return super(GymFaceidLog, self).create(vals_list)
