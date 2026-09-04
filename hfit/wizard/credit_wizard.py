from odoo import models, fields, api
from odoo.exceptions import UserError
import base64

class AccountMoveExportWizard(models.TransientModel):
    _name = 'account.move.export.wizard'
    _description = 'Exportar facturas a TXT'

    file_data = fields.Binary('Archivo', readonly=True)
    file_name = fields.Char('Nombre del archivo', readonly=True)

    generation_date = fields.Date(string='Fecha de Generacion',default=fields.Date.context_today)
    cc_group_id = fields.Many2one(comodel_name='subscription.group', string='Grupo')
    cc_brand_id = fields.Many2one(comodel_name='credit.card.brand', string='Marca Tarjeta')
    sequence_header = fields.Integer(string='Secuencia Header')
    sequence_detail = fields.Integer(string='Secuencia Detalle')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            invoices = self.env['account.move'].browse(active_ids)
            brand_ids = invoices.mapped('brand_id')
            group_ids = invoices.mapped('cc_group_id')
            if len(brand_ids) == 1:
                res['cc_brand_id'] = brand_ids.id
                brand = self.env['credit.card.brand'].browse(brand_ids.id)
                res['sequence_header'] = brand.sequence_header_id.number_next_actual
                res['sequence_detail']  = brand.sequence_detail_id.number_next_actual   
            if len(group_ids) == 1:
                res['cc_group_id'] = group_ids.id                     
        return res

    def export_txt_file(self):
        active_ids = self.env.context.get('active_ids', [])
        invoices = self.env['account.move'].browse(active_ids)

        if not invoices:
            raise UserError("No hay facturas seleccionadas.")

        if any(inv.payment_state == 'paid' for inv in invoices):
            raise UserError("Solo se permiten facturas NO pagadas.")

        brands = invoices.mapped('brand_id')
        if len(brands) != 1:
            raise UserError("Las facturas deben tener el mismo brand_id.")

        
        file = self.env['credit.card.file.so'].create({
            'generation_date': self.generation_date,
            'cc_group_id': self.cc_group_id.id,
            'cc_brand_id': self.cc_brand_id.id,
            'sequence_header': self.sequence_header,
            'sequence_detail': self.sequence_detail,
        }).generate_file()

        file_name = 'facturas_exportadas.txt'

        encoded_file = base64.b64encode(file.get('file_data').decode('utf-8').encode('utf-8'))

        self.write({
            'file_data': encoded_file,
            'file_name': file_name,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.export.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
