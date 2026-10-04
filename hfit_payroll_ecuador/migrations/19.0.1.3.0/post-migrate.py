from odoo import SUPERUSER_ID, api
from odoo.tools import convert_file


def migrate(cr, version):
    # Las reglas salariales pasaron a noupdate="1": las actualizaciones ya no
    # reescriben los registros existentes. Se cargan una última vez en modo
    # init para aplicar los cambios de esta versión (SOBRET en los aportes
    # IESS y el décimo tercero, y la regla en la estructura).
    env = api.Environment(cr, SUPERUSER_ID, {})
    convert_file(env, 'hfit_payroll_ecuador', 'data/hr_salary_rule_data.xml',
                 None, mode='init', noupdate=True)
