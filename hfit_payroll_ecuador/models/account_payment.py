from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    payslip_ids = fields.Many2many(
        'hr.payslip', 'hr_payslip_account_payment_rel', 'payment_id', 'payslip_id',
        string='Nóminas', copy=False, readonly=True,
        help='Nóminas que se pagaron con este pago.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        payments = super().create(vals_list)
        # El asistente de pagos no envía cuenta bancaria cuando el asiento de
        # origen (la nómina) no tiene una: se usa la primera del contacto.
        for pay in payments:
            if pay.payment_type == 'outbound' and not pay.partner_bank_id:
                pay.partner_bank_id = pay.partner_id.bank_ids[:1]
        return payments
