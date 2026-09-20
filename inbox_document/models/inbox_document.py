import logging
from datetime import datetime

from lxml import etree
from markupsafe import Markup

from odoo import Command, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Mapeo tabla 17 del SRI (codigoPorcentaje del IVA) -> account.tax.group.l10n_ec_type
L10N_EC_VAT_SUBTAXES = {
    '0': 'zero_vat',
    '2': 'vat12',
    '3': 'vat14',
    '4': 'vat15',
    '5': 'vat05',
    '6': 'not_charged_vat',
    '7': 'exempt_vat',
    '8': 'vat08',
    '10': 'vat13',
}

# Tabla 16 del SRI (codigo del impuesto)
L10N_EC_TAX_CODES = {
    '2': 'vat',
    '3': 'ice',
    '5': 'irbpnr',
}


def find_text(node, path, default=''):
    """Devuelve el texto de ``path`` bajo ``node``, o ``default`` si no existe."""
    if node is None:
        return default
    found = node.find(path)
    if found is None or found.text is None:
        return default
    return found.text.strip()


class InboxDocument(models.Model):
    _name = 'inbox.document'
    _description = 'Documento de Entrada (SRI)'
    _inherit = ['mail.thread']
    _rec_name = 'numero_comprobante'
    _order = 'fecha_emision desc, id desc'

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )
    clave_acceso = fields.Char(string='Clave de Acceso', copy=False, index=True)
    numero_autorizacion = fields.Char(string='Número Autorización', copy=False)
    fecha_autorizacion = fields.Datetime(string='Fecha Autorización')
    tipo_documento = fields.Many2one(
        comodel_name='l10n_latam.document.type',
        string='Tipo Documento',
    )
    estado = fields.Selection(
        string='Estado',
        selection=[
            ('cargado', 'Cargado'),
            ('consultado', 'Consultado'),
            ('procesado', 'Procesado'),
            ('error', 'Error'),
        ],
        default='cargado',
        tracking=True,
    )
    xml_recibido = fields.Text(string='XML Recibido')

    # ===== Cabecera obtenida del XML (fuente de verdad) =====
    numero_comprobante = fields.Char(string='Número Comprobante')
    ruc_emisor = fields.Char(string='RUC Emisor')
    partner_id = fields.Many2one(comodel_name='res.partner', string='Proveedor', index=True)
    partner_name = fields.Char(string='Razón Social Emisor')
    fecha_emision = fields.Date(string='Fecha Emisión')
    total = fields.Float(string='Total')
    info_adicional = fields.Text(string='Información Adicional')

    line_ids = fields.One2many(
        comodel_name='inbox.document.xml.detail',
        inverse_name='document_id',
        string='Líneas del XML',
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

    invoice_id = fields.Many2one(comodel_name='account.move', string='Factura', copy=False)

    # ===================================================================================
    # Helpers
    # ===================================================================================

    def crear_nota(self, mensaje=False):
        if not mensaje:
            return
        self.message_post(
            body=Markup('<p>%s</p>') % mensaje.strip(),
            subtype_xmlid='mail.mt_note',
            message_type='comment',
        )

    def _get_xml_tree(self):
        """Devuelve el nodo raíz del comprobante (``factura`` o ``notaCredito``).

        Soporta tanto el XML del comprobante directo como la respuesta de autorización
        del SRI, que trae el comprobante embebido en un CDATA bajo ``<comprobante>``.
        """
        self.ensure_one()
        if not self.xml_recibido:
            return None
        # etree no acepta str con declaración de encoding: hay que pasarle bytes.
        tree = etree.fromstring(self.xml_recibido.encode('utf-8'))
        if tree.tag in ('factura', 'notaCredito'):
            return tree
        comprobante = tree.findtext('.//comprobante')
        if comprobante:
            return etree.fromstring(comprobante.encode('utf-8'))
        return tree

    def _find_tax(self, codigo, codigo_porcentaje, tarifa):
        """Resuelve el ``account.tax`` de compra a partir de los códigos del SRI.

        En Odoo 19 ``l10n_ec_type`` vive en ``account.tax.group`` (ya no en
        ``account.tax``) y el campo ``l10n_ec_code_sri`` dejó de existir, por lo que
        el matching se hace por el tipo ecuatoriano del grupo de impuesto.
        """
        self.ensure_one()
        tax_kind = L10N_EC_TAX_CODES.get(codigo)
        if tax_kind in ('ice', 'irbpnr'):
            ec_type = tax_kind
        else:
            ec_type = L10N_EC_VAT_SUBTAXES.get(codigo_porcentaje)
            if not ec_type:
                # Fallback por tarifa: 15 -> vat15, 0 -> zero_vat
                try:
                    rate = int(float(tarifa or 0))
                except ValueError:
                    rate = 0
                ec_type = 'zero_vat' if rate == 0 else 'vat%02d' % rate
        return self.env['account.tax'].search([
            ('tax_group_id.l10n_ec_type', '=', ec_type),
            ('type_tax_use', '=', 'purchase'),
            ('company_id', 'parent_of', self.company_id.id),
        ], limit=1), ec_type

    def _find_product(self, code):
        """Homologa el código del XML contra el producto del proveedor.

        Solo se usa cuando ``agrupar`` está desactivado.
        """
        self.ensure_one()
        if not code or not self.partner_id:
            return self.env['product.product']
        supplierinfo = self.env['product.supplierinfo'].search([
            ('partner_id', '=', self.partner_id.id),
            ('product_code', '=', code),
        ], limit=1)
        if supplierinfo.product_id:
            return supplierinfo.product_id
        if supplierinfo.product_tmpl_id:
            return supplierinfo.product_tmpl_id.product_variant_id
        return self.env['product.product'].search([('default_code', '=', code)], limit=1)

    # ===================================================================================
    # Parseo del XML
    # ===================================================================================

    def _get_default_account(self, account_type):
        """Primera cuenta contable de la compañía con el tipo indicado."""
        self.ensure_one()
        AccountAccount = self.env['account.account']
        return AccountAccount.with_company(self.company_id).search([
            *AccountAccount._check_company_domain(self.company_id),
            ('account_type', '=', account_type),
        ], limit=1)

    def _prepare_partner_vals(self, ruc, razon_social):
        """Vals del proveedor creado a partir de la ``infoTributaria`` del XML."""
        self.ensure_one()
        vals = {
            'name': razon_social or ruc,
            'vat': ruc,
            'company_type': 'company',
            'l10n_latam_identification_type_id': self.env.ref('l10n_ec.ec_ruc').id,
            'email' : 'sincorreo@company.com'
        }
        payable = self._get_default_account('liability_payable')
        if payable:
            vals['property_account_payable_id'] = payable.id
        receivable = self._get_default_account('asset_receivable')
        if receivable:
            vals['property_account_receivable_id'] = receivable.id
        return vals

    def _create_partner(self, ruc, razon_social):
        self.ensure_one()
        return self.env['res.partner'].with_company(self.company_id).create(
            self._prepare_partner_vals(ruc, razon_social)
        )

    def _prepare_line_vals(self, line_nodes, is_credit_note=False):
        """Construye los vals de ``inbox.document.xml.detail`` desde los nodos ``detalle``."""
        self.ensure_one()
        line_vals = []
        missing_taxes = set()
        missing_products = set()

        for node in line_nodes:
            code_field = 'codigoInterno' if is_credit_note else 'codigoPrincipal'
            product_code = find_text(node, code_field)
            description = find_text(node, 'descripcion')

            tax_ids = []
            for tax_node in node.findall('.//impuestos/impuesto'):
                codigo = find_text(tax_node, 'codigo')
                codigo_porcentaje = find_text(tax_node, 'codigoPorcentaje')
                tarifa = find_text(tax_node, 'tarifa')
                tax, ec_type = self._find_tax(codigo, codigo_porcentaje, tarifa)
                if tax:
                    tax_ids.append(tax.id)
                else:
                    missing_taxes.add(
                        'código %s / porcentaje %s (tipo esperado: %s)'
                        % (codigo, codigo_porcentaje, ec_type)
                    )

            vals = {
                'name': ' '.join(filter(None, [product_code, description])),
                'product_code': product_code,
                'quantity': float(find_text(node, 'cantidad', '0') or 0),
                'price_unit': float(find_text(node, 'precioUnitario', '0') or 0),
                'discount_amount': float(find_text(node, 'descuento', '0') or 0),
                'tax_ids': [Command.set(tax_ids)],
            }

            if not self.agrupar:
                product = self._find_product(product_code)
                if product:
                    vals['product_id'] = product.id
                elif product_code:
                    missing_products.add(product_code)

            line_vals.append(Command.create(vals))

        if missing_taxes:
            self.sudo().crear_nota(
                'Los siguientes impuestos no se encuentran registrados en el sistema: %s.'
                % ', '.join(sorted(missing_taxes))
            )
        if missing_products:
            self.sudo().crear_nota(
                'No se pudo homologar los siguientes códigos de producto: %s.'
                % ', '.join(sorted(missing_products))
            )
        return line_vals, bool(missing_taxes or missing_products)

    def _parse_info_adicional(self, tree):
        campos = tree.findall('.//infoAdicional/campoAdicional')
        if not campos:
            return False
        return '\n'.join(
            '%s: %s' % (campo.get('nombre') or '', (campo.text or '').strip())
            for campo in campos
        ).strip()

    def _parse_comprobante(self, tree, is_credit_note=False):
        """Extrae cabecera y líneas del comprobante y las escribe en el registro."""
        self.ensure_one()
        info_tributaria = tree.find('.//infoTributaria')
        info_node = tree.find('.//infoNotaCredito' if is_credit_note else './/infoFactura')

        ruc_emisor = find_text(info_tributaria, 'ruc')
        partner_name = find_text(info_tributaria, 'razonSocial')
        partner = self.env['res.partner'].search([('vat', '=', ruc_emisor)], limit=1)
        if not partner and ruc_emisor:
            partner = self._create_partner(ruc_emisor, partner_name)
            self.sudo().crear_nota(
                'El proveedor "%s" con RUC "%s" no estaba registrado y fue creado automáticamente.'
                % (partner_name, ruc_emisor)
            )

        numero_comprobante = '-'.join([
            find_text(info_tributaria, 'estab'),
            find_text(info_tributaria, 'ptoEmi'),
            find_text(info_tributaria, 'secuencial'),
        ])
        fecha_emision = find_text(info_node, 'fechaEmision')
        total = find_text(info_node, 'importeTotal') or find_text(info_node, 'valorModificacion')

        vals = {
            'ruc_emisor': ruc_emisor,
            'partner_id': partner.id,
            'partner_name': partner_name,
            'numero_comprobante': numero_comprobante,
            'clave_acceso': find_text(info_tributaria, 'claveAcceso') or self.clave_acceso,
            'info_adicional': self._parse_info_adicional(tree),
        }
        if fecha_emision:
            vals['fecha_emision'] = datetime.strptime(fecha_emision, '%d/%m/%Y').date()
        if total:
            vals['total'] = float(total)

        # El partner debe estar escrito antes de homologar productos.
        self.write(vals)

        line_nodes = tree.findall('.//detalles/detalle')
        line_vals, has_warnings = self._prepare_line_vals(line_nodes, is_credit_note)
        self.write({'line_ids': [Command.clear()] + line_vals})
        return has_warnings

    def procesar_xml(self):
        dt_invoice = self.env.ref('l10n_ec.ec_dt_01')
        dt_credit_note = self.env.ref('l10n_ec.ec_dt_04')
        for rec in self:
            if not rec.xml_recibido:
                continue
            try:
                tree = rec._get_xml_tree()
                if tree is None:
                    continue
                if rec.tipo_documento == dt_invoice:
                    has_warnings = rec._parse_comprobante(tree)
                    rec._link_existing_move('in_invoice', has_warnings)
                elif rec.tipo_documento == dt_credit_note:
                    has_warnings = rec._parse_comprobante(tree, is_credit_note=True)
                    rec._link_existing_move('in_refund', has_warnings)
                else:
                    rec.sudo().crear_nota(
                        'El tipo de documento "%s" no está soportado; solo se procesan '
                        'facturas y notas de crédito.' % (rec.tipo_documento.display_name or '')
                    )
            except Exception as error:  # noqa: BLE001 - se registra en el chatter
                _logger.exception('Error procesando el XML de %s', rec.clave_acceso)
                rec.estado = 'error'
                rec.sudo().crear_nota(str(error))

    def _link_existing_move(self, move_type, has_warnings=False):
        """Vincula el documento con un ``account.move`` ya existente, si lo hubiera.

        ``l10n_latam_document_number`` no está almacenado ni es buscable, así que se
        filtra por ``name`` (que lo contiene, precedido del prefijo del tipo de
        documento) y se compara el número exacto en memoria.
        """
        self.ensure_one()
        if not self.numero_comprobante:
            self.estado = 'error' if has_warnings else 'consultado'
            return
        candidates = self.env['account.move'].search([
            ('name', 'like', self.numero_comprobante),
            ('move_type', '=', move_type),
            ('state', '!=', 'cancel'),
            ('commercial_partner_id.vat', '=', self.ruc_emisor),
            ('company_id', '=', self.company_id.id),
        ])
        move = candidates.filtered(
            lambda m: m.l10n_latam_document_number == self.numero_comprobante
        )[:1]
        if move:
            self.invoice_id = move
            self.estado = 'procesado'
        else:
            self.estado = 'error' if has_warnings else 'consultado'

    def reprocesar_xml(self):
        model_document_import = self.env['inbox.document.import']
        for rec in self:
            model_document_import.consultar_ws_con_clave_acceso(rec)
        self.procesar_xml()

    # ===================================================================================
    # Generación del account.move
    # ===================================================================================

    def _get_line_taxes(self, line, fiscal_position=None):
        """Impuestos definitivos de una línea, ya mapeados por la posición fiscal."""
        taxes = line.tax_ids
        if line.product_id:
            taxes |= line.product_id.supplier_taxes_id
        if taxes and fiscal_position:
            taxes = fiscal_position.map_tax(taxes)
        return taxes

    def _prepare_invoice_line_vals(self, fiscal_position=None):
        """Devuelve los comandos de ``invoice_line_ids`` a partir de las líneas del XML."""
        self.ensure_one()
        if self.agrupar:
            return self._prepare_grouped_invoice_line_vals(fiscal_position)

        commands = []
        for line in self.line_ids:
            taxes = self._get_line_taxes(line, fiscal_position)
            vals = {
                'quantity': line.quantity,
                'price_unit': line.price_unit,
                'discount': line.discount,
                'tax_ids': [Command.set(taxes.ids)],
            }
            if line.product_id:
                vals['product_id'] = line.product_id.id
            if line.name:
                vals['name'] = line.name
            commands.append(Command.create(vals))
        return commands

    def _prepare_grouped_invoice_line_vals(self, fiscal_position=None):
        """Una sola ``account.move.line`` por cada combinación de impuestos.

        Las líneas del XML que comparten exactamente los mismos impuestos se suman
        en un único renglón, con cantidad 1 y el subtotal neto (ya descontado) como
        precio unitario.
        """
        self.ensure_one()
        currency = self.company_id.currency_id
        groups = {}
        for line in self.line_ids:
            taxes = self._get_line_taxes(line, fiscal_position)
            key = tuple(sorted(taxes.ids))
            group = groups.setdefault(key, {'taxes': taxes, 'subtotal': 0.0})
            group['subtotal'] += line.quantity * line.price_unit - line.discount_amount

        commands = []
        for group in groups.values():
            taxes = group['taxes']
            commands.append(Command.create({
                'name': ', '.join(taxes.mapped('name')) or 'Sin impuestos',
                'quantity': 1.0,
                'price_unit': currency.round(group['subtotal']),
                'discount': 0.0,
                'tax_ids': [Command.set(taxes.ids)],
            }))
        return commands

    def _get_move_type(self):
        self.ensure_one()
        if self.tipo_documento == self.env.ref('l10n_ec.ec_dt_04'):
            return 'in_refund'
        return 'in_invoice'

    def _prepare_invoice_vals(self):
        self.ensure_one()
        fiscal_position = self.partner_id.with_company(
            self.company_id
        ).property_account_position_id
        return {
            'company_id': self.company_id.id,
            'move_type': self._get_move_type(),
            'partner_id': self.partner_id.id,
            'invoice_date': self.fecha_emision,
            'l10n_latam_document_type_id': self.tipo_documento.id,
            'l10n_latam_document_number': self.numero_comprobante,
            'autorizacion': self.numero_autorizacion or self.clave_acceso,
            'narration': self.info_adicional,
            'inbox_invoice_id': self.id,
            'invoice_line_ids': self._prepare_invoice_line_vals(fiscal_position),
        }

    def create_invoice(self):
        for rec in self:
            if rec.estado == 'procesado':
                continue
            if not rec.line_ids:
                raise UserError(
                    'El documento "%s" no tiene líneas procesadas del XML.'
                    % (rec.numero_comprobante or rec.clave_acceso)
                )
            if not rec.partner_id:
                raise UserError(
                    'El documento "%s" no tiene proveedor asignado.'
                    % (rec.numero_comprobante or rec.clave_acceso)
                )
            move = self.env['account.move'].with_company(rec.company_id).create(
                rec._prepare_invoice_vals()
            )
            rec.invoice_id = move
            rec.estado = 'procesado'
            rec.sudo().crear_nota('Documento creado: %s.' % move.display_name)

    def unlink(self):
        procesados = self.filtered(lambda doc: doc.estado == 'procesado')
        if procesados:
            raise ValidationError(
                'No se pueden eliminar registros en estado "Procesado": %s'
                % ', '.join(procesados.mapped(lambda d: d.numero_comprobante or d.clave_acceso))
            )
        return super().unlink()
