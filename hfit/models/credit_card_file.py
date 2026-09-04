# -*- coding: utf-8 -*-

from typing import Sequence
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import base64
import tempfile
import os
from io import BytesIO
import logging

try:
    import openpyxl
    import xlrd
except Exception:
    openpyxl = None

_logger = logging.getLogger(__name__)

class CreditCardFileSO(models.Model):
    _name = 'credit.card.file.so'
    _description = 'Archivo de Tarjetas SO'
    _inherit = ['mail.thread', 'mail.activity.mixin']


    generation_date = fields.Date(string='Fecha de Generacion',default=fields.Date.context_today)
    cc_group_id = fields.Many2one(comodel_name='subscription.group', string='Grupo')

    cc_brand_ids = fields.Many2many(comodel_name='credit.card.brand', string='Marcas Tarjeta')

    cc_branch_id = fields.Many2one(comodel_name='res.branch', string='Sucursal')

    sequence_header = fields.Integer(string='Secuencia Header')
    sequence_detail = fields.Integer(string='Secuencia Detalle')
 
    invoice_ids = fields.Many2many('account.move', 
                                   string='Facturas')


    @api.onchange('cc_brand_id')
    def on_change_cc_brand_id(self):
        pass

    def generate_file(self):


        header_format = "1{codigo_establecimeinto}{fecha}{lote}{nombre_establecimeinto}\n"
        detail_format = "2{tarjeta}{filler3}{codigo_transaccion}{fecha}{hora}{vale}{codigo_aprobacion}{monto}{autorizacion}{tipo_credito}{cuota}{tipo_lectura}{tipo_moneda}{iva}{servicio}{propina}{interes}{valor1}{codigo_promo}{puntos_promo}{ice}{otros}{valor2}{filler}{vencimiento_tarjeta}{filler200}{cap_12}{cap_0}{opcional}\n"
        footer_format = "3{codigo_establecimeinto}{fecha}{lote}{total}\n"

        for brand in self.cc_brand_ids:
            header = {}
            lst_body = []
            footer = {}
        
            count = 0
            sequence_header = brand.sequence_header_id.number_next_actual

            header_txt = header_format.format(codigo_establecimeinto = "000" + self.cc_branch_id.collect_datacard_code + "00",
                fecha=datetime.strftime(datetime.strptime(self.generation_date.__str__(), "%Y-%m-%d"),"%y%m%d"),
                lote=str(sequence_header).zfill(15),
                nombre_establecimeinto=self.env.user.company_id.name)

            hoy = fields.Datetime.from_string(fields.Datetime.now())

            # las que rebotaron en el intento anterior debo ponerles algun estado para volver a intentar


            #debo enviar las facturas en borrador de suscripciones 
            # el grupo debo calcular por las fechas  ej grupo 1 del 1 al 7 de cada mes, grupo 2 del 8 al 15, etc
            # no importa el grupo de la factura sino la fecha de la factura
            # ademas debo sumar las facturas de suscripciones que quedaron pendientes  de cobros de meses anteriores

            facturas_borrador = self.env['account.move'].search([           
                ('brand_id.id','=',brand.id),          
                ('branch_id.id','=',self.cc_branch_id.id),
                ('state','=','draft'),
                ('estado_cobro','in',['pendiente','fallido']),
                ('move_type','=','out_invoice'),
                ], order='id asc')

            # Agregar las facturas encontradas a este archivo
            if facturas_borrador:
                # mantener la relación many2many con las facturas procesadas
                self.invoice_ids = [(4, fid.id) for fid in facturas_borrador]

                self.invoice_ids.write({'estado_cobro': 'transito'})


            for record in facturas_borrador:
                intento = record.intentos + 1
                record.write({'intentos' : intento})

                count+=1
                subtotal = round(float(record.amount_total) / float(1.15),2)
                subtotal_str = str(int(round(subtotal * 100,2)))
                iva = round(record.amount_total  - subtotal,2)
                print('a')

                order_id = record.invoice_line_ids.mapped('sale_line_ids').mapped('order_id')

                detail_txt = detail_format.format(tarjeta=order_id.cc_number_stored.replace(" ","").ljust(19), 
                    filler3="", codigo_transaccion="003000",
                    fecha = datetime.strftime(datetime.strptime(self.generation_date.__str__(), "%Y-%m-%d"),"%y%m%d"),
                    hora="000000", 
                    vale= str(record.id).zfill(15), 
                    codigo_aprobacion="000000",
                    monto = str(int(record.amount_total*100)).zfill(13), autorizacion="1",
                    tipo_credito= "00",cuota ="00" , tipo_lectura="012" , tipo_moneda= "840",
                    iva= str(int(round(iva*100))).zfill(13)  , servicio = "0000000000000" , propina="0000000000000" , interes="0000000000000" , 
                    valor1 = "0000000000000",
                    codigo_promo="00",
                    puntos_promo= "000" , ice= "0000000000000" , otros= "0000000000000" ,
                    valor2 = "0000000000000",  filler = "           " ,
                    vencimiento_tarjeta= datetime.strftime(datetime.strptime(order_id.expiration_date.__str__(), "%Y-%m-%d"),"%Y%m"),
                    filler200 = " ".ljust(200) ,cap_12 = str(int(subtotal_str)).zfill(14) ,
                    cap_0= "00000000000000", 
                    opcional = "00000000000000"            
                    )
                lst_body.append(detail_txt)

                #secuencial +=1

                #record.write({'cobrado' : True, 'fecha_cobro' : self.generation_date})

            footer_txt = footer_format.format(codigo_establecimeinto = "00000" + self.cc_branch_id.collect_datacard_code,
                fecha=datetime.strftime(datetime.strptime(self.generation_date.__str__(), "%Y-%m-%d"),"%y%m%d"),
                lote=str(sequence_header).zfill(7),
                total = str(count).zfill(6)
                )
            #VISA_HFIT_JUL2021_2.txt
            file_name = "{tarjeta}_HFIT_{anio}_{grupo}_{code}.txt".format(tarjeta= brand.name,
                grupo = self.cc_group_id.name[-1:],
                anio = datetime.strftime(datetime.strptime(self.generation_date.__str__(), "%Y-%m-%d"),"%b%Y"),
                code = self.cc_branch_id.collect_datacard_code
            )

            path_file = tempfile.gettempdir() + '/' + file_name

            if os.path.exists(path_file):
                os.remove(path_file)

            with open(path_file, 'a') as the_file:
                the_file.write(header_txt)

                for line in lst_body:
                    the_file.write(line)

                the_file.write(footer_txt)
        
            with open(path_file, 'rb') as myfile:
                data = myfile.read()

            self.message_post(
                attachments=[('%s' % file_name, data)],
                body="",
            )

            brand.sequence_header_id.next_by_id()
            #brand.sequence_detail_id.number_next = secuencial
            #brand.sequence_detail_id._set_number_next_actual()
        # Retornar referencia al archivo para descarga
        return {
            'file_name': file_name,
            'file_path': path_file,
            'file_data': data,
        }

    def action_open_invoices(self):
        """Abrir las facturas relacionadas con este archivo en una acción de ventana."""
        self.ensure_one()
        invoice_ids = self.invoice_ids
        if not invoice_ids:
            return {'type': 'ir.actions.act_window_close'}
        tree_view = self.env.ref('account.view_move_tree')
        form_view = self.env.ref('account.view_move_form')
        return {
            'name': 'Facturas asociadas',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'views': [(tree_view.id, 'tree'), (form_view.id, 'form')],
            'domain': [('id', 'in', invoice_ids.ids)],
            'target': 'current',
        }


    def cancel_file(self):
        pass

class UploadReturnedExcelWizard(models.TransientModel):
    _name = 'hfit.upload.returned.excel'
    _description = 'Cargar Excel de devueltos'

    credit_card_file_id = fields.Many2one('credit.card.file.so', string='Archivo Procesado')
    file = fields.Binary(string='Archivo Excel', required=True)
    filename = fields.Char(string='Nombre de archivo')

    def action_process_file(self):
        """Procesa el archivo Excel (hoja 1) y toma los IDs en la columna 3 para marcar las facturas como 'fallido' en campo estado_cobro."""
        self.ensure_one()

        if openpyxl is None:
            raise ValidationError('La librería openpyxl no está disponible en el entorno. Instala openpyxl para poder procesar archivos Excel.')

        if not self.file:
            raise ValidationError('No se subió ningún archivo.')

        data = base64.b64decode(self.file)
        bio = BytesIO(data)
        rows_iterator = None
        filename = (self.filename or '').lower()
        prefer_xlrd = filename.endswith('.xls')

        try:
            book = xlrd.open_workbook(file_contents=data)
            sheet = book.sheet_by_index(1)
            def _iter_xlrd_rows():
                for r in range(sheet.nrows):
                    yield sheet.row_values(r)
            rows_iterator = _iter_xlrd_rows()
        except Exception as e:
            raise ValidationError(f'Error al leer el archivo Excel con xlrd: {e}')


        # {inv_id: descripcion} para facturas fallidas
        failed_invoices = {}
        col_estado = None
        col_descripcion = None
        lst_invoices = []

        for row in rows_iterator:
            try:
                if col_estado is None:
                    indices_resp = [i for i, e in enumerate(row) if e == 'RESPUESTA']
                    indices_desc = [i for i, e in enumerate(row) if e == 'DESCRIPCION']
                    if indices_resp:
                        col_estado = indices_resp[0]
                    if indices_desc:
                        col_descripcion = indices_desc[0]
                    continue

                estado_devolucion = row[col_estado]
                val = row[5]
            except Exception:
                val = None
            if val is None:
                continue

            try:
                inv_id = int(val)
                lst_invoices.append(inv_id)
            except Exception as e1:
                continue    
            
            try:
                estado_devolucion = str(estado_devolucion).strip().lower()
                if estado_devolucion != 'devuelto':
                    continue # solo me interesan los devueltos para marcar como fallidos

            except Exception:
                print(f"Error al procesar estado de devolución para factura {inv_id}: {estado_devolucion}")                

            descripcion = ''
            if col_descripcion is not None:
                try:
                    descripcion = str(row[col_descripcion]).strip()
                except Exception:
                    descripcion = ''
            failed_invoices[inv_id] = descripcion

        _logger.info(f'Facturas a marcar como fallidas: {list(failed_invoices.keys())}')

        Invoice = self.env['account.move']

        # Marcar fallidas con su descripcion
        if failed_invoices:
            for inv_id, descripcion in failed_invoices.items():
                invoice = Invoice.browse(inv_id)
                if invoice.exists():
                    invoice.write({'estado_cobro': 'fallido', 'descripcion_cobro': descripcion})
                    orders = invoice.invoice_line_ids.mapped('sale_line_ids').mapped('order_id')
                    if orders:
                        orders.bloquear_usuario()
    
        if self:
            success_invoices = [item for item in lst_invoices if item not in set(failed_invoices.keys())]
            Invoice = self.env['account.move']
            success_invoices = Invoice.browse(success_invoices)            
            if success_invoices:
                success_invoices.write({'estado_cobro': 'exito'})

        active_id = self._context.get('active_id')
        if active_id:
            model = self.env['credit.card.file.so']
            record = model.browse(active_id)
            if record.exists():
                record.message_post(
                    body=f"Archivo procesado {self.filename}.  Facturas marcadas como fallidas: {set(failed_invoices.keys())}.",
                )
        return {'type': 'ir.actions.act_window_close'}
