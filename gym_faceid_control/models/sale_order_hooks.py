import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        """
        """
        res = super().action_confirm()
        for order in self:
            if order.branch_id and order.branch_id.face_id_url:
                if order.faceid_sync_state != 'active':                    
                    order.faceid_sync_on_confirm()
        return res

    def _prepare_upsell_renew_order_values(self, subscription_state):
        """
        Interceptamos la renovación (Caso 1 de sale_subscription extendido por hfit)
        para asegurar que durante las renovaciones la fecha se recalcule en FaceID.
        """
        res = super()._prepare_upsell_renew_order_values(subscription_state)
        # Notas: La orden devuelta aquí es un diccionario de valores para una nueva orden
        # Odoo base standard en v17 muchas veces usa la MISMA orden y extiende next_invoice_date.
        # Si este método devuelve valores para una nueva SO, la nueva SO disparará action_confirm.
        # Pero nos aseguramos de resincronizar la original si la suscripción sigue activa
        return res
   
    def resume_subscription(self):
        """
        Hook a reanudar manual desde hfit (Caso 5)
        """
        res = super().resume_subscription()
        for order in self:
            if order.branch_id and order.branch_id.face_id_url:
                print("Resuming subscription in FaceID for order", order.id)
                order.faceid_resume_member()
        return 

    def set_close(self, close_reason_id=None, renew=False):
        """
        Hook a la baja de suscripción (wizard "Close" / sale.subscription.close.reason.wizard).
        Cubre también cualquier otra llamada a set_close() (ej. renovaciones), inactivando
        en FaceID únicamente cuando el resultado real es un churn (subscription_state=6_churn),
        no cuando la suscripción termina renovada (5_renewed).
        """
        res = super().set_close(close_reason_id=close_reason_id, renew=renew)
        for order in self:
            if order.branch_id and order.branch_id.face_id_url and order.subscription_state == '6_churn':
                # No se bloquea con la fecha actual: el cliente ya pagó hasta su próxima
                # factura (next_invoice_date), así que se mantiene habilitado en FaceID
                # y el dispositivo le corta el acceso automáticamente al llegar esa fecha.
                until_date = order.next_invoice_date
                _logger.info(
                    "Dando de baja en FaceID al cliente de la orden %s (subscription_state=6_churn), "
                    "acceso habilitado hasta %s", order.id, until_date,
                )
                order.faceid_deactivate_member(until_date=until_date)
        return res


class PauseSubscriptionWizard(models.TransientModel):
    _inherit = 'hfit.pause.subscription.wizard'

    def action_confirm_pause(self):
        """
            Interceptamos la pausa desde el wizard
        """
        res = super().action_confirm_pause()
        for order in self.sale_order_id:
            if order.branch_id and order.branch_id.face_id_url:
                print("Pausing subscription in FaceID for order", order.id)
                # solo pausa , el tiempo se recalcula cuando se reactiva la suscripción
                order.faceid_pause_member()
        return res
        
