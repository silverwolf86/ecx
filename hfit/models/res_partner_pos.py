from odoo import api, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _load_pos_data_read(self, records, config):
        """Además de los campos estándar cargados al POS, adjunta a cada
        partner el id del empleado asociado (si existe), para que el frontend
        pueda validar los pagos por descuento a rol (is_payroll_discount)."""
        partners = super()._load_pos_data_read(records, config)
        if not partners:
            return partners

        partner_ids = [p['id'] for p in partners]
        employees = self.env['hr.employee'].sudo().search_read(
            [('work_contact_id', 'in', partner_ids)],
            fields=['work_contact_id'],
        )
        # Map partner_id → first employee id found
        partner_employee_map = {}
        for emp in employees:
            pid = emp['work_contact_id'][0]
            if pid not in partner_employee_map:
                partner_employee_map[pid] = emp['id']

        for partner in partners:
            partner['pos_employee_id'] = partner_employee_map.get(partner['id'], False)

        return partners
