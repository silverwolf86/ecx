import base64
import logging
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InboxDocumentImport(models.TransientModel):
    _name = 'inbox.document.import'
    _description = 'Importar archivo TXT de comprobantes electrónicos del SRI'

    name = fields.Char(string='Archivo.txt')
    txt = fields.Binary(string='Archivo TXT')
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        default=lambda self: self.env.company,
        readonly=True,
    )
    agrupar = fields.Boolean(
        string='Agrupar líneas por impuesto',
        default=True,
        help='Si está activo, al crear el documento se genera una sola línea por cada '
             'combinación de impuestos, sumando los subtotales netos, y se ignora el '
             'código de producto del XML. Si está desactivado, se genera una línea por '
             'cada detalle del XML y se homologa cada una contra el producto del '
             'proveedor (product.supplierinfo).',
    )

    def importar_archivo_txt(self):
        # Layout del TXT del portal del SRI (índices tal como los consume este parser):
        # 00: RUC_EMISOR          03: SERIE_COMPROBANTE   04: CLAVE_ACCESO
        # 05: FECHA_AUTORIZACION  06: FECHA_EMISION       07: IDENTIFICACION_RECEPTOR
        # 10: IMPORTE_TOTAL
        self.ensure_one()
        if not self.txt:
            raise ValidationError('No ha cargado ningún archivo.')

        company = self.company_id or self.env.company
        company_vat = company.partner_id.vat or ''
        if not company_vat:
            raise ValidationError(
                'La compañía "%s" no tiene RUC configurado.' % company.display_name
            )

        model_document = self.env['inbox.document']
        model_document_type = self.env['l10n_latam.document.type']

        txt_read = base64.b64decode(self.txt).decode('latin-1')
        documento = model_document.browse()
        for fila in txt_read.split('\n'):
            if '\t' not in fila:
                if fila.strip() and documento:
                    # Línea suelta posterior a un comprobante: es su importe total.
                    try:
                        documento.total = float(fila.strip())
                    except ValueError:
                        pass
                continue

            campos = fila.split('\t')
            if len(campos) < 11:
                continue
            receptor = campos[7]
            if not (receptor and receptor.isnumeric()):
                continue
            if receptor not in (company_vat, company_vat[:10]):
                raise ValidationError(
                    'El archivo no corresponde al RUC %s de la compañía %s.'
                    % (company_vat, company.display_name)
                )

            clave_acceso = campos[4]
            if not clave_acceso:
                continue
            if model_document.search_count([('clave_acceso', '=', clave_acceso)], limit=1):
                continue

            document_type = model_document_type.search([
                ('code', '=', clave_acceso[8:10]),
                ('country_id', '=', self.env.ref('base.ec').id),
            ], limit=1)
            if not document_type:
                continue

            documento = model_document.create({
                'numero_comprobante': campos[3] or False,
                'ruc_emisor': campos[0] or False,
                'company_id': company.id,
                'fecha_emision': self._parse_date(campos[6], '%d/%m/%Y'),
                'fecha_autorizacion': self._parse_date(campos[5], '%d/%m/%Y %H:%M:%S'),
                'tipo_documento': document_type.id,
                'clave_acceso': clave_acceso,
                'agrupar': self.agrupar,
                'total': float(campos[10] or 0),
            })
            self.consultar_ws_con_clave_acceso(documento)
            documento.procesar_xml()

        return self.render_inbox_document()

    @api.model
    def _parse_date(self, value, fmt):
        if not value:
            return False
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            return False

    @api.model
    def consultar_ws_con_clave_acceso(self, documento):
        """Consulta la autorización del comprobante al SRI y guarda su XML.

        Reutiliza el cliente SOAP de ``ecx_edi`` (zeep), que respeta el ambiente
        de pruebas/producción configurado en la compañía.
        """
        if documento.xml_recibido:
            return True

        response, errors, warnings = self.env['account.edi.format']._l10n_ec_get_client_service_response_new(
            documento.company_id,
            'authorization',
            claveAccesoComprobante=documento.clave_acceso,
        )
        if errors or warnings:
            documento.estado = 'error'
            documento.sudo().crear_nota('\n'.join(errors + warnings))
            return False

        try:
            autorizaciones = response['autorizaciones'] and response['autorizaciones']['autorizacion'] or []
        except (AttributeError, TypeError, KeyError) as error:
            documento.estado = 'error'
            documento.sudo().crear_nota('Respuesta inesperada del SRI: %s' % error)
            return False

        if not isinstance(autorizaciones, list):
            autorizaciones = [autorizaciones]
        if not autorizaciones:
            documento.estado = 'error'
            documento.sudo().crear_nota(
                'La clave de acceso "%s" no se encuentra autorizada.' % documento.clave_acceso
            )
            return False

        autorizacion = autorizaciones[0]
        _logger.info(
            'SRI: estado de autorización %s para %s',
            autorizacion['estado'], documento.clave_acceso,
        )
        if autorizacion['estado'] != 'AUTORIZADO':
            documento.estado = 'error'
            documento.sudo().crear_nota(
                'El SRI devolvió el estado "%s" para la clave "%s".\n%s'
                % (autorizacion['estado'], documento.clave_acceso,
                   self._format_sri_messages(autorizacion))
            )
            return False

        fecha_autorizacion = autorizacion['fechaAutorizacion']
        if isinstance(fecha_autorizacion, datetime) and fecha_autorizacion.tzinfo:
            fecha_autorizacion = fecha_autorizacion.replace(tzinfo=None)

        documento.write({
            'xml_recibido': autorizacion['comprobante'],
            'numero_autorizacion': autorizacion['numeroAutorizacion'] or documento.clave_acceso,
            'fecha_autorizacion': fecha_autorizacion or documento.fecha_autorizacion,
            'estado': 'consultado',
        })
        return True

    @api.model
    def _format_sri_messages(self, autorizacion):
        mensajes = autorizacion['mensajes']
        if not mensajes:
            return ''
        mensajes = getattr(mensajes, 'mensaje', mensajes)
        if not isinstance(mensajes, list):
            mensajes = [mensajes]
        return '\n'.join(
            ' - '.join(filter(None, [
                msg['identificador'], msg['mensaje'], msg['informacionAdicional'], msg['tipo'],
            ]))
            for msg in mensajes
        )

    def render_inbox_document(self):
        action = self.env['ir.actions.actions']._for_xml_id('inbox_document.inbox_document_action')
        return action
