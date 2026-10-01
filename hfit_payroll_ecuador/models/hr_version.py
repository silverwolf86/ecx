from odoo import fields, models


class HrVersion(models.Model):
    # En Odoo 19 hr.contract fue reemplazado por hr.version; la variable
    # `contract` de las reglas salariales es un registro hr.version.
    _inherit = 'hr.version'

    part_time_percentage = fields.Float(
        string='% Jornada',
        default=1.0,
        help='1.0 = tiempo completo, 0.5 = medio tiempo, etc. '
             'Afecta el cálculo del Décimo Cuarto (se calcula sobre SBU, no sobre contract.wage).',
    )
    decimo13_mensual = fields.Boolean(
        string='Décimo Tercero Mensualizado',
        default=True,
        help='Si está marcado, el décimo tercero se paga prorrateado cada mes junto al sueldo. '
             'Si no, se acumula para pago en diciembre (no cubierto por esta estructura todavía).',
    )
    decimo14_mensual = fields.Boolean(
        string='Décimo Cuarto Mensualizado',
        default=True,
        help='Igual que decimo13_mensual pero para el décimo cuarto sueldo.',
    )
    fondos_reserva_acumula = fields.Boolean(
        string='Fondos de Reserva Acumulados en IESS',
        default=False,
        help='Si está marcado, los fondos de reserva NO se pagan mensualmente al empleado: '
             'se depositan/acumulan en el IESS. Si no está marcado, se pagan mensual junto al neto.',
    )
