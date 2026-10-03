from odoo import api, fields, models


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

    # En los contratos de empleados el nombre es el contacto + fecha de
    # inicio; las plantillas (sin empleado) conservan su nombre manual.
    name = fields.Char(compute='_compute_name', store=True, readonly=False)

    @api.depends('employee_id.work_contact_id.name', 'employee_id.name',
                 'contract_date_start', 'date_version')
    def _compute_name(self):
        for version in self:
            employee = version.employee_id
            if not employee:
                version.name = version.name
                continue
            date_start = version.contract_date_start or version.date_version
            version.name = ' '.join(filter(None, [
                employee.work_contact_id.name or employee.name,
                date_start and date_start.strftime('%d/%m/%Y'),
            ]))

    @api.model_create_multi
    def create(self, vals_list):
        # Una versión nueva se crea copiando la anterior: se descarta el
        # nombre copiado para que se calcule con su propia fecha de inicio.
        for vals in vals_list:
            if vals.get('employee_id'):
                vals.pop('name', None)
        return super().create(vals_list)

    @api.depends('name')
    def _compute_display_name(self):
        # Odoo muestra solo la fecha en las versiones de empleados; aquí se
        # muestra el nombre (contacto + fecha de inicio).
        super()._compute_display_name()
        for version in self:
            if version.employee_id and version.name:
                version.display_name = version.name
