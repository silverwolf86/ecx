from odoo import models, api, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_faceid_retry_sync(self):
        """ Botón manual para reintentar la sincronización de FaceID """
        for order in self:
            if order.faceid_sync_state in ['pending', 'error']:
                # Lanza el trabajo a la cola si se tiene queue_job, o síncrono
                # order.with_delay(description="FaceID Sync Retry").faceid_activate_member()
                order.faceid_activate_member()
        return True
