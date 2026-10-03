from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # `name` de hr.version pasó a ser calculado: se llena en los contratos
    # existentes de empleados.
    env = api.Environment(cr, SUPERUSER_ID, {})
    versions = env['hr.version'].with_context(active_test=False).search(
        [('employee_id', '!=', False)])
    versions._compute_name()
