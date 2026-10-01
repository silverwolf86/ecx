from odoo import _, models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_register_payment_payslip(self):
        """Abre el asistente estándar de pagos sobre la línea del NET del
        asiento de cada nómina. El asistente crea un account.payment por
        empleado y lo concilia con esa línea."""
        not_posted = self.filtered(lambda s: s.state != 'done' or not s.move_id)
        if not_posted:
            raise UserError(_(
                'Solo se pueden pagar nóminas confirmadas con asiento contable:\n%s',
                '\n'.join(not_posted.mapped('display_name'))))
        lines = self.env['account.move.line']
        for slip in self:
            # Solo la cuenta crédito de la regla NET: las provisiones y otros
            # pasivos por pagar del empleado no forman parte del neto a pagar.
            net_account = slip.line_ids.filtered(
                lambda l: l.code == 'NET').salary_rule_id.account_credit_id
            if not net_account:
                raise UserError(_(
                    'La regla NET de la nómina %s no tiene cuenta crédito.',
                    slip.display_name))
            partner = slip.employee_id.work_contact_id
            lines |= slip.move_id.line_ids.filtered(
                lambda l: l.account_id in net_account
                and l.partner_id == partner
                and l.parent_state == 'posted'
                and not l.reconciled)
        if not lines:
            raise UserError(_(
                'No hay saldos pendientes por pagar a los empleados en las '
                'nóminas seleccionadas. Verifique que estén sin pagar y que la '
                'cuenta crédito de la regla NET sea de tipo "Por pagar".'))
        return lines.action_register_payment()
