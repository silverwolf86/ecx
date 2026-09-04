from odoo import models, fields, api


class VirtuagymLog(models.Model):
    _name = 'virtuagym.log'
    _description = 'Virtuagym API Synchronization Log'
    _order = 'create_date desc'

    name = fields.Char(
        string='Referencia', required=True, copy=False, readonly=True,
        index=True, default=lambda self: 'New Log',
    )

    action = fields.Selection([
        ('check', 'Buscar Miembro'),
        ('create', 'Crear Miembro'),
        ('update', 'Actualizar Miembro'),
        ('membership', 'Crear Membresía'),
    ], string='Acción', required=True, readonly=True)

    request_url = fields.Char(string='URL', readonly=True)
    payload = fields.Text(string='Payload Enviado', readonly=True)
    status_code = fields.Char(string='Código de Estado', readonly=True)
    response_text = fields.Text(string='Respuesta', readonly=True)

    branch_id = fields.Many2one('res.branch', string='Sucursal', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Orden de Venta', readonly=True)

    state = fields.Selection([
        ('ok', 'Éxito'),
        ('error', 'Error'),
    ], string='Estado', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'New Log':
                action_str = dict(self._fields['action'].selection).get(vals.get('action'), 'Unknown')
                vals['name'] = f"Virtuagym - {action_str}"
        return super().create(vals_list)
