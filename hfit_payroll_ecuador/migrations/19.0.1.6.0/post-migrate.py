from odoo import SUPERUSER_ID, api

CODE = """sbu = 482.0  # TODO: mover a ir.config_parameter
# Días trabajados del mes comercial, deducidos del BASIC (wage / 30 × días)
dias = categories.BASIC / contract.wage * 30 if contract.wage else 0
# Base: el sueldo del período, con piso del SBU proporcional a los días
# trabajados (el sueldo ya incluye la jornada parcial). El sobretiempo NO
# entra en el aporte patronal.
base_aporte = max(categories.BASIC, sbu * dias / 30)
result = base_aporte * 0.1115"""


def migrate(cr, version):
    # Las reglas son noupdate="1": se actualiza solo la fórmula del aporte
    # patronal (sin sobretiempo) sin tocar el resto de reglas.
    env = api.Environment(cr, SUPERUSER_ID, {})
    rule = env.ref('hfit_payroll_ecuador.hr_salary_rule_iesspatr_ec', raise_if_not_found=False)
    if rule:
        rule.amount_python_compute = CODE
