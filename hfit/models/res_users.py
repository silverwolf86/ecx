from odoo import models, fields, api
import requests

class ResUsers(models.Model):
    _inherit = 'res.users'
    
    branch_id = fields.Many2one(comodel_name='res.branch', string='Sucursal', 
                                       required=False)
    
    branch_ids = fields.Many2many(comodel_name='res.branch', string='Sucursales')

    @api.model
    def write(self, vals):
        res = super().write(vals)
        if 'branch_id' in vals:
            # Limpia el caché de reglas y el entorno actual
            self.env['ir.rule'].clear_caches()
            self.env.invalidate_all()

            # Si cambió su propia rama (por ejemplo, el admin que se edita a sí mismo)
            # podemos forzar la recarga del registro en el entorno
            #if self.env.uid in self.ids:
            #    # Refresca la información del usuario en el entorno actual
            #    self.env.user.invalidate_cache(fnames=['branch_id'], ids=[self.env.uid])
        return res