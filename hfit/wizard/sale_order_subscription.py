from odoo import models, fields, api
from odoo.exceptions import UserError,ValidationError
from datetime import datetime, timedelta

import base64

MIN_DAYS_PAUSE = 90
MAX_DAYS_PAUSE = 30

class PauseSubscriptionWizard(models.TransientModel):
    _name = 'hfit.pause.subscription.wizard'
    _description = 'Wizard para pausar suscripción'

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', required=True)
    start_date = fields.Date(string='Fecha Inicio', required=True)
    end_date = fields.Date(string='Fecha Fin', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super(PauseSubscriptionWizard, self).default_get(fields_list)
        so = self.env.context.get('active_id') and self.env['sale.order'].browse(self.env.context.get('active_id'))
        if so:
            res['sale_order_id'] = so.id
        return res

    def action_confirm_pause(self):
        self.ensure_one()
        if self.end_date < self.start_date:
            raise ValidationError('La fecha fin no puede ser anterior a la fecha inicio.')
        so = self.sale_order_id
        if not so:
            raise ValidationError('No se encontró la orden para pausar.')
        dias = (datetime.now().date() - fields.Date.from_string(so.start_date)).days
        if dias < MIN_DAYS_PAUSE:
            raise ValidationError('La suscripción debe tener al menos 90 días activos para poder pausarla.')
        
        # Calcular diferencia en días entre start_date y end_date
        try:
            start_dt = fields.Date.from_string(self.start_date)
            end_dt = fields.Date.from_string(self.end_date)
            diff_days = (end_dt - start_dt).days

            if diff_days > MAX_DAYS_PAUSE:
                raise ValidationError('La pausa no puede ser mayor a 30 días.')

            so.write({
                'pause_start_date': self.start_date,
                'pause_end_date': self.end_date,
                'subscription_state': '4_paused',
                #'next_invoice_date': so.next_invoice_date + timedelta(days=diff_days) if so.next_invoice_date else False,
            })


        except Exception as e:
            print(f"Error al calcular diferencia de días: {str(e)}")

        return {'type': 'ir.actions.act_window_close'}

        
