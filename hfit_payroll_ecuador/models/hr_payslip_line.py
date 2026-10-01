from odoo import models


class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    def _get_partner_id(self, credit_account):
        # Cybrosys solo usa el partner de la contribution register. Si la regla
        # no tiene una y la cuenta es por cobrar/pagar, usamos el contacto del
        # empleado para poder pagar y conciliar por partner.
        partner_id = super()._get_partner_id(credit_account)
        if partner_id:
            return partner_id
        account = (self.salary_rule_id.account_credit_id if credit_account
                   else self.salary_rule_id.account_debit_id)
        if account.account_type in ('asset_receivable', 'liability_payable'):
            return self.slip_id.employee_id.work_contact_id.id or None
        return None
