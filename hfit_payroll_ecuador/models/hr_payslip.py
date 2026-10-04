from datetime import datetime, time

import babel.dates

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    payment_ids = fields.Many2many(
        'account.payment', 'hr_payslip_account_payment_rel', 'payslip_id', 'payment_id',
        string='Pagos', copy=False, readonly=True,
        help='Pagos registrados contra el asiento de esta nómina.',
    )

    def _get_payslip_name(self, employee, date_from):
        locale = self.env.context.get('lang') or 'en_US'
        period = babel.dates.format_date(
            date=datetime.combine(fields.Date.to_date(date_from), time.min),
            format='MMMM-y', locale=locale)
        return _('Nomina de %(employee)s para %(period)s',
                 employee=employee.name, period=period)

    def _get_default_struct(self):
        """Primera estructura salarial que se encuentre."""
        return self.env['hr.payroll.structure'].search([], limit=1)

    def _get_struct_inputs(self, struct, contract, date_from, date_to):
        """Igual que get_inputs, pero para una estructura que no es la del
        contrato."""
        rule_ids = struct._get_parent_structure().get_all_rules()
        sorted_rule_ids = [rule_id for rule_id, _sequence in
                           sorted(rule_ids, key=lambda x: x[1])]
        inputs = self.env['hr.salary.rule'].browse(sorted_rule_ids).input_ids
        return [{
            'name': rule_input.name,
            'code': rule_input.code,
            'contract_id': contract.id,
            'date_from': date_from,
            'date_to': date_to,
        } for rule_input in inputs]

    # Inputs que toda nómina debe tener, con monto 0 para llenarlos a mano.
    DEFAULT_INPUT_XMLIDS = (
        'hfit_payroll_ecuador.hr_rule_input_bono_ec',
        'hfit_payroll_ecuador.hr_rule_input_desc_ec',
        'hfit_payroll_ecuador.hr_rule_input_sobretiempo_ec',
    )

    @api.model
    def _add_default_inputs(self, inputs, contracts, date_from, date_to):
        """Agrega a la lista de dicts `inputs` los inputs por defecto que
        falten, uno por contrato."""
        rule_inputs = self.env['hr.rule.input']
        for xmlid in self.DEFAULT_INPUT_XMLIDS:
            rule_inputs |= self.env.ref(xmlid, raise_if_not_found=False) or rule_inputs
        existing = {(line['code'], line['contract_id']) for line in inputs}
        for contract in contracts:
            for rule_input in rule_inputs:
                if (rule_input.code, contract.id) not in existing:
                    inputs.append({
                        'name': rule_input.name,
                        'code': rule_input.code,
                        'amount': 0.0,
                        'contract_id': contract.id,
                        'date_from': date_from,
                        'date_to': date_to,
                    })
        return inputs

    @api.model
    def get_inputs(self, contracts, date_from, date_to):
        inputs = super().get_inputs(contracts, date_from, date_to)
        return self._add_default_inputs(inputs, contracts, date_from, date_to)

    def _ensure_default_inputs(self):
        for slip in self:
            contract = slip.contract_id or self.env['hr.version'].browse(
                self.get_contract(slip.employee_id, slip.date_from, slip.date_to)[:1])
            if not contract:
                continue
            existing = [{'code': line.code, 'contract_id': line.contract_id.id}
                        for line in slip.input_line_ids]
            missing = self._add_default_inputs(
                list(existing), contract, slip.date_from, slip.date_to)[len(existing):]
            if missing:
                slip.write({'input_line_ids': [(0, 0, vals) for vals in missing]})

    @api.model_create_multi
    def create(self, vals_list):
        slips = super().create(vals_list)
        slips._ensure_default_inputs()
        return slips

    def write(self, vals):
        res = super().write(vals)
        if 'contract_id' in vals:
            # Los inputs siguen al contrato de la nómina.
            for slip in self.filtered('contract_id'):
                slip.input_line_ids.filtered(
                    lambda line: line.contract_id != slip.contract_id
                ).write({'contract_id': slip.contract_id.id})
        return res

    def onchange_employee_id(self, date_from, date_to, employee_id=False,
                             contract_id=False):
        res = super().onchange_employee_id(
            date_from, date_to, employee_id=employee_id, contract_id=contract_id)
        if not employee_id or not date_from or not date_to:
            return res
        value = res['value']
        value['name'] = self._get_payslip_name(
            self.env['hr.employee'].browse(employee_id), date_from)
        if not value.get('struct_id'):
            # El contrato no tiene estructura: se usa la primera que exista.
            # El método original termina antes de calcular días e inputs.
            struct = self._get_default_struct()
            value['struct_id'] = struct.id
            contract = self.env['hr.version'].browse(value.get('contract_id'))
            if struct and contract:
                value.update({
                    'worked_days_line_ids': self.get_worked_day_lines(
                        contract, date_from, date_to),
                    'input_line_ids': self._add_default_inputs(
                        self._get_struct_inputs(struct, contract, date_from, date_to),
                        contract, date_from, date_to),
                })
        return res

    @api.onchange('employee_id')
    def onchange_employee(self):
        res = super().onchange_employee()
        if not self.employee_id or not self.date_from or not self.date_to:
            return res
        self.name = self._get_payslip_name(self.employee_id, self.date_from)
        if not self.struct_id:
            self.struct_id = self._get_default_struct()
        return res

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
