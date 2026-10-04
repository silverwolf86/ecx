from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Relaciona las nóminas ya pagadas con sus pagos, a partir de la
    # conciliación del asiento de la nómina.
    env = api.Environment(cr, SUPERUSER_ID, {})
    for slip in env['hr.payslip'].search([('move_id', '!=', False)]):
        lines = slip.move_id.line_ids
        counterparts = (lines.matched_debit_ids.debit_move_id
                        | lines.matched_credit_ids.credit_move_id)
        payments = counterparts.move_id.origin_payment_id
        if payments:
            slip.payment_ids = payments
