from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_inform_payment_state_to_faceid(self, state):
        """
        Método semántico de dominio para avisar a FaceID de cambios en el estado de cobro.
        state debe ser 'fallido' o 'exito'.
        Este método DEBE ser llamado por la lógica de cobranza (ej. cron o botón), 
        no a través de overrides de persistencia (write).
        """
        for move in self:
            if move.move_type == 'out_invoice':
                orders = move.invoice_line_ids.mapped('sale_line_ids.order_id')
                for order in orders:
                    # Alternativa a _async_faceid_sync
                    if state == 'fallido':
                        # order.with_delay(description="FaceID Sync: Payment Failed").faceid_mark_payment_failed()
                        order.faceid_mark_payment_failed()
                    elif state == 'exito':
                        # order.with_delay(description="FaceID Sync: Payment Success").faceid_reactivate_member()
                        order.faceid_reactivate_member()
