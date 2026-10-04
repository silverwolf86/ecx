from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _compute_can_group_payments(self):
        # Cada nómina debe generar su propio pago (una línea por empleado en
        # el archivo del banco): no se ofrece la opción de agrupar pagos.
        super()._compute_can_group_payments()
        Payslip = self.env['hr.payslip'].sudo()
        for wizard in self:
            if wizard.can_group_payments and Payslip.search_count(
                    [('move_id', 'in', wizard.line_ids.move_id.ids)], limit=1):
                wizard.can_group_payments = False

    def _init_payments(self, to_process, edit_mode=False):
        payments = super()._init_payments(to_process, edit_mode=edit_mode)
        # Relaciona cada pago con las nóminas cuyos asientos está pagando.
        # sudo: quien paga puede no tener acceso a hr.payslip.
        Payslip = self.env['hr.payslip'].sudo()
        for vals in to_process:
            payslips = Payslip.search(
                [('move_id', 'in', vals['to_reconcile'].move_id.ids)])
            if payslips:
                vals['payment'].sudo().payslip_ids = payslips
        return payments
