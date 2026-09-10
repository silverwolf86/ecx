import requests
from datetime import datetime, timedelta
from markupsafe import Markup, escape
import re
from werkzeug.urls import url_join, url_quote, url_encode
import logging
import base64
from dateutil.relativedelta import relativedelta
from psycopg2.extensions import TransactionRollbackError
from ast import literal_eval
from collections import defaultdict
import traceback

from odoo import fields, models, _, api, Command, SUPERUSER_ID, modules
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero
from odoo.osv import expression
from odoo.tools import config, format_amount, plaintext2html, split_every, str2bool
from odoo.tools.date_utils import get_timedelta
from odoo.tools.misc import format_date

_logger = logging.getLogger(__name__)


SUBSCRIPTION_PROGRESS_STATE = ['3_progress', '4_paused']

class SubscriptionGroup(models.Model):
    _name = 'subscription.group'
    _description = 'Grupo Subscripcion'
    _rec_name = "name"

    name = fields.Char(string='Marca')

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    cc_group_id = fields.Many2one(comodel_name='subscription.group', string='Grupo', tracking=True)
    cc_brand_id = fields.Many2one(comodel_name='credit.card.brand', string='Marca Tarjeta',tracking=True)
    cc_cardholdername = fields.Char(string='Nombre Tarjetahabiente',required=False,tracking=True)
    expiration_date = fields.Date(string='Fecha Expiracion Tarjeta',required=False,tracking=True)
    cc_number = fields.Char(string='Tarjeta',required=False,tracking=True)

    cc_number_stored = fields.Char(string="Número de Tarjeta Almacenado", copy=False)

    cc_number_display = fields.Char(
        string="Número de Tarjeta",
        compute='_compute_cc_number_display',
        store=False,
        help="Muestra los dígitos de la tarjeta."
    )

    cc_number_input = fields.Char(
        string="Actualizar Tarjeta",
        store=False, 
        inverse='_inverse_cc_number_input',
        copy=False,
        help="Ingrese el número completo solo para cambiarlo. Se borrará después de guardar."
    )

    cc_history_ids = fields.One2many(
        'sale.order.cc.history', 
        'order_id', 
        string="Historial de Cambios de Tarjeta"
    )

    referencia_pago = fields.Char(string='Referencia de Pago',required=False,tracking=True)
    
    l10n_ec_sri_payment_id = fields.Many2one(
        comodel_name="l10n_ec.sri.payment",
        string="Payment Method (SRI)",
    )

    @api.depends('cc_number_stored')
    def _compute_cc_number_display(self):
        """Calcula la versión enmascarada del número de tarjeta."""
        for order in self:
            if order.cc_number_stored and len(order.cc_number_stored) > 4:
                last_four = order.cc_number_stored[-4:]
                first_four = order.cc_number_stored[:4]
                order.cc_number_display = f"{first_four} **** **** {last_four}"
            else:
                order.cc_number_display = "No establecido"

    def _inverse_cc_number_input(self):
        """
        Guarda el número de tarjeta del campo de entrada en el campo de almacenamiento
        y crea un registro en el historial de cambios.
        """
        for order in self:
            # Continuar solo si se ingresó un valor y es diferente al actual
            if order.cc_number_input and order.cc_number_input != order.cc_number_stored:
                
                # Guarda el nuevo valor en el campo de almacenamiento
                order.cc_number_stored = order.cc_number_input
                
                # Crea la entrada en el historial de cambios
                self.env['sale.order.cc.history'].create({
                    'order_id': order.id,
                    'user_id': self.env.user.id,
                    'change_date': fields.Datetime.now(),
                    'new_value_masked': order.cc_number_input,
                })

    def _validate_cc_number(self, card_number):
        if not card_number:
            return
        card_clean = re.sub(r'[\s\-]', '', card_number)
        if not card_clean.isdigit():
            raise UserError(_('El número de tarjeta no debe contener caracteres especiales, solo dígitos.'))
        if len(card_clean) < 12:
            raise UserError(_('El número de tarjeta debe tener al menos 12 dígitos.'))

    def write(self, vals):
        """
        Sobrescribe el método de escritura para limpiar el campo de entrada
        después de que el valor ha sido procesado.
        """
        if 'cc_number_stored' in vals or 'cc_number' in vals:
            card_number = vals.get('cc_number_stored') or vals.get('cc_number')
            self._validate_cc_number(card_number)

        res = super(SaleOrder, self).write(vals)

        if 'cc_number_input' in vals and vals['cc_number_input'] is not False:
            self.write({'cc_number_input': False})

        return res


    branch_id = fields.Many2one(
        'res.branch', 
        string='Sucursal', 
        tracking=True,
        default=lambda self: self.env.user.branch_id.id
    )
    start_date = fields.Date(string='Start Date',                             
                             readonly=False,
                             store=True,
                             tracking=True,
                             help="The start date indicate when the subscription periods begin.")
    # Campos para controlar pausas
    pause_start_date = fields.Date(string='Pause Start', readonly=False, tracking=True)
    pause_end_date = fields.Date(string='Pause End', readonly=False, tracking=True)


    def action_cancel(self):
        for order in self:
            pending = order.invoice_ids.filtered(
                lambda inv: inv.move_type == 'out_invoice' and (
                    inv.state == 'draft' or
                    (inv.state == 'posted' and inv.payment_state not in ('paid', 'in_payment', 'reversed'))
                )
            )
            if pending:
                names = '\n'.join(inv.name or str(inv.id) for inv in pending)
                raise UserError(
                    'No se puede cancelar la orden porque tiene facturas pendientes o sin pagar:\n\n%s\n\n'
                    'Por favor, cancele primero esas facturas e intente de nuevo.' % names
                )
        return super().action_cancel()

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        for order in self:

            #validar si el plan es de 3600 debe haber tomado otro plan anterior debe pedir confirmacion del usuario de si o no
            #

            # Validar formato del número de tarjeta si fue registrado
            order._validate_cc_number(order.cc_number_stored or order.cc_number)

            # Validar que el mismo socio no tenga otra sale.order activa (suscripción)
            if order.plan_id:
                # si es recurrente ahi los campos de tarjeta son obligatorios
                if order.branch_id.id != 1:
                    if not order.cc_number_display or not order.cc_cardholdername or not order.expiration_date:
                        raise UserError('Para planes de suscripción, los campos de tarjeta son obligatorios.')

                active_orders = self.env['sale.order'].search([
                    ('partner_id', '=', order.partner_id.id),
                    ('subscription_state', '=', 'open'),
                    ('id', '!=', order.id)
                ])
                if active_orders:
                    raise UserError('El socio ya tiene una suscripción activa (sale.order).')

                ## sincronizar con virtuagym
                try:
                    # si es que no existe el cliente en virtuagym lo creamos
                    order.partner_id.sync_virtuagym_member(order.branch_id)
                    # y le asignamos la membresía correspondiente al plan vendido
                    order.sync_virtuagym_membership()

                except Exception as e:
                    print(f"Error al sincronizar con Virtuagym: {str(e)}")

            # Recalcular estado de suscripción según si el producto es recurrente
            has_recurring = order._has_recurring_product()
            if has_recurring:
                if order.subscription_state not in ('3_progress', '4_paused', '5_kicked', '6_churn'):
                    order.subscription_state = '3_progress'
            else:
                if order.subscription_state in SUBSCRIPTION_PROGRESS_STATE:
                    order.subscription_state = '1_draft'

        return res
    
    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals['cc_group_id'] = self.cc_group_id.id if self.cc_group_id else False
        vals['brand_id'] = self.cc_brand_id.id if self.cc_brand_id else False     
        vals['branch_id']= self.branch_id.id if self.branch_id else False

        journal_id = self.env['account.journal'].search([('branch_id','=',self.branch_id.id),('type','=','sale')], limit=1 )

        vals['journal_id']= journal_id.id or False

        if self.l10n_ec_sri_payment_id:
            vals['l10n_ec_sri_payment_id'] = self.l10n_ec_sri_payment_id.id
        if self.referencia_pago:
            vals['payment_reference'] = self.referencia_pago
        if self.l10n_ec_sri_payment_id.code == "01":
            #si es effectivo 
            journal_id = self.env['account.journal'].search([('code','=','extra')], limit=1 )
            vals['journal_id'] = journal_id.id or False
        return vals

    def _create_recurring_invoice(self, batch_size=30):
        moves = super(SaleOrder, self)._create_recurring_invoice(batch_size=batch_size)
        # Pasar los campos de grupo y marca a la factura
        for move in moves:
            order = move.invoice_line_ids.subscription_id
            move.write({
                'cc_group_id': order.cc_group_id.id if order.cc_group_id else False,
                'brand_id': order.cc_brand_id.id if order.cc_brand_id else False,      
                'branch_id': order.branch_id.id if order.branch_id else False,                
            })
        return moves

    def action_sync_virtuagym(self):
        try:
            self.partner_id.sync_virtuagym_member(self.branch_id)
            self.sync_virtuagym_membership()

        except Exception as e:
            raise UserError(f"Error al sincronizar: {str(e)}")
        return True

    # PARCHE TEMPORAL: mientras exista una segunda instancia de Virtuagym (Veintimilla),
    # sus membership_id no se guardan en virtuagym_membership_id (reservado para Armenia)
    # sino en el barcode del producto. Quitar este bloque cuando Veintimilla tenga su propio
    # campo o se unifique en una sola cuenta de Virtuagym.
    VIRTUAGYM_VEINTIMILLA_BRANCH_ID = 2

    def _get_virtuagym_membership_id(self):
        """Busca en las líneas de la orden el primer producto que tenga configurado
        un Virtuagym Membership ID, que es la definición de membresía a asignar.
        En Veintimilla (parche temporal) se toma del barcode del producto en lugar
        del campo virtuagym_membership_id."""
        self.ensure_one()
        is_veintimilla = self.branch_id.id == self.VIRTUAGYM_VEINTIMILLA_BRANCH_ID
        for line in self.order_line:
            if is_veintimilla:
                try:
                    membership_id = int(line.product_id.barcode)
                except (TypeError, ValueError):
                    continue
            else:
                membership_id = line.product_id.product_tmpl_id.virtuagym_membership_id
            if membership_id:
                return membership_id
        return False

    # Valores aceptados por la API de Virtuagym en el campo payment_method.
    # Confirmados por la propia API, que rechaza cualquier otro con:
    #   "Field 'payment_method' must be one of: cash, bank_transfer, card_terminal, not_paid"
    # OJO: 'card' NO es válido; enviarlo hace que la creación de la membresía falle.
    VIRTUAGYM_PAYMENT_METHODS = ('cash', 'bank_transfer', 'card_terminal', 'not_paid')

    # Mapeo explícito forma de pago SRI -> payment_method de Virtuagym.
    # Códigos según el catálogo de l10n_ec (l10n_ec.sri.payment):
    #   01 No use of the financial system (efectivo)          -> cash
    #   15 Offset of Debts (compensación, no hubo cobro real) -> not_paid
    #   16 Debit Card                                         -> card_terminal
    #   19 Credit Card                                        -> card_terminal
    #   20 Others with use of the financial system (transf.)  -> bank_transfer
    VIRTUAGYM_PAYMENT_METHOD_BY_SRI_CODE = {
        '01': 'cash',
        '15': 'not_paid',
        '16': 'card_terminal',
        '19': 'card_terminal',
        '20': 'bank_transfer',
    }
    # Valor usado cuando la orden no tiene forma de pago SRI informada o trae un
    # código fuera del catálogo esperado. Se asume 'cash' porque la venta ya está
    # confirmada (hubo cobro) y marcarla 'not_paid' podría afectar el estado del
    # socio en Virtuagym. Cada uso queda registrado como warning.
    VIRTUAGYM_PAYMENT_METHOD_FALLBACK = 'cash'

    def _get_virtuagym_payment_method(self):
        """Traduce la forma de pago SRI de la orden al payment_method que espera
        la API de Virtuagym (ver VIRTUAGYM_PAYMENT_METHODS para los valores válidos).
        """
        self.ensure_one()
        code = self.l10n_ec_sri_payment_id.code

        if not code:
            _logger.warning(
                "_get_virtuagym_payment_method: la orden %s no tiene forma de pago SRI "
                "informada; se envía '%s' a Virtuagym por defecto.",
                self.name, self.VIRTUAGYM_PAYMENT_METHOD_FALLBACK,
            )
            return self.VIRTUAGYM_PAYMENT_METHOD_FALLBACK

        payment_method = self.VIRTUAGYM_PAYMENT_METHOD_BY_SRI_CODE.get(code)
        if not payment_method:
            _logger.warning(
                "_get_virtuagym_payment_method: forma de pago SRI %s (%s) sin mapeo a "
                "Virtuagym en la orden %s; se envía '%s'.",
                code, self.l10n_ec_sri_payment_id.name, self.name,
                self.VIRTUAGYM_PAYMENT_METHOD_FALLBACK,
            )
            return self.VIRTUAGYM_PAYMENT_METHOD_FALLBACK

        return payment_method

    def sync_virtuagym_membership(self):
        """Crea en Virtuagym la membership instance (contrato) correspondiente al
        producto vendido en esta orden, para el socio ya sincronizado."""
        self.ensure_one()

        membership_id = self._get_virtuagym_membership_id()
        if not membership_id:
            _logger.info(
                "sync_virtuagym_membership: la orden %s no tiene ningún producto con "
                "Virtuagym Membership ID configurado, se omite la creación de membresía.",
                self.name,
            )
            return False

        salesperson_id = self.branch_id.virtuagym_salesperson_id
        if not salesperson_id:
            _logger.warning(
                "sync_virtuagym_membership: la sucursal %s no tiene Virtuagym Salesperson ID "
                "configurado, se omite la creación de membresía para la orden %s.",
                self.branch_id.name, self.name,
            )
            return False

        start_date = self.start_date or self.date_order.date()
        is_created, _contract_id, msg = self.partner_id.create_virtuagym_membership_instance(
            branch=self.branch_id,
            membership_id=membership_id,
            start_date=start_date.strftime('%Y-%m-%d'),
            payment_method=self._get_virtuagym_payment_method(),
            salesperson_id=salesperson_id,
            sale_order=self,
        )
        if not is_created:
            _logger.warning(
                "sync_virtuagym_membership: error al crear la membresía en Virtuagym para "
                "la orden %s: %s", self.name, msg,
            )
        return is_created
    
    def identificar_marca_tarjeta(self, numero_tarjeta):
        """
        Identifica la marca de una tarjeta de crédito basándose en su número.

        Args:
            numero_tarjeta (str): El número de la tarjeta de crédito como una cadena de texto.

        Returns:
            str: La marca de la tarjeta (Visa, Mastercard, Diners Club) o "Marca no reconocida".
        """
        # Elimina espacios en blanco y guiones del número de tarjeta
        numero_tarjeta = re.sub(r'\s+|-', '', numero_tarjeta)

        # Verifica que el número de tarjeta contenga solo dígitos
        if not numero_tarjeta.isdigit():
            return "Número de tarjeta inválido. Por favor, ingrese solo dígitos."

        # --- Reglas de Identificación ---

        # Diners Club
        # Comienza con 300-305, 36 o 38 y tiene 14 dígitos.
        if (numero_tarjeta.startswith(('300', '301', '302', '303', '304', '305')) and len(numero_tarjeta) == 14) or \
        (numero_tarjeta.startswith('36') and len(numero_tarjeta) == 14) or \
        (numero_tarjeta.startswith('38') and len(numero_tarjeta) == 14):
            return "D1"

        # Visa
        # Comienza con 4 y tiene 13 o 16 dígitos.
        elif numero_tarjeta.startswith('4') and (len(numero_tarjeta) == 13 or len(numero_tarjeta) == 16):
            return "V1"

        # Mastercard
        # Comienza con un número entre 51 y 55 y tiene 16 dígitos.
        elif (int(numero_tarjeta[0:2]) >= 51 and int(numero_tarjeta[0:2]) <= 55) and len(numero_tarjeta) == 16:
            return "M1"
            
        else:
            return False

    # @api.onchange('partner_id')
    # def _onchange_partner_id(self):
    #     if self.partner_id:
    #         self.cc_cardholdername = self.partner_id.name

    @api.onchange('cc_number_input')
    def _onchange_cc_number(self):
        if self.cc_number_input:
            marca = self.identificar_marca_tarjeta(self.cc_number_input)
            if marca:
                brand = self.env['credit.card.brand'].search([('code', '=', marca)], limit=1)
                self.cc_brand_id = brand.id if brand else False

    @api.onchange('order_line')
    def _onchange_order_line_set_plan(self):
        for line in self.order_line:
            if getattr(line.product_id, 'recurring_invoice', False):
                plan = self.env['sale.subscription.plan'].search([('name', 'ilike', 'mensual')], limit=1)
                if plan:
                    self.plan_id = plan.id
                break
    
    def _compute_start_date(self):
        super()._compute_start_date()
        for so in self:
            if not so.is_subscription:
                so.start_date = False
            elif not so.start_date:
                so.start_date = so.date_order


    @api.model
    def default_get(self, fields_list):
        res = super(SaleOrder, self).default_get(fields_list)
        if 'branch_id' in fields_list and not res.get('branch_id'):
            branch = self.env.user.branch_id
            if branch:
                res['branch_id'] = branch.id
        return res
    
    def _has_recurring_product(self):
        """Devuelve True si la orden tiene al menos una línea con producto recurrente.
        Soporta tanto el booleano de sale_subscription (product_template.recurring_invoice)
        como un posible campo custom x_is_recurring si lo usas.
        """
        self.ensure_one()
        for line in self.order_line:
            pt = line.product_id.product_tmpl_id
            # sale_subscription estándar
            if hasattr(pt, 'recurring_invoice') and pt.recurring_invoice:
                return True
            # fallback: campo custom
            if hasattr(pt, 'x_is_recurring') and pt.x_is_recurring:
                return True
            # (Opcional) si usas plantillas de suscripción:
            if hasattr(pt, 'subscription_template_id') and pt.subscription_template_id:
                return True
        return False
    
    def _get_authorization_report(self):
        """Obtiene el ir.actions.report por nombre técnico del template."""
        report = self.env['ir.actions.report']._get_report_from_name('hfit.report_authorization_template')
        if not report:
            raise UserError(_("No se encontró el reporte hfit.report_authorization_template"))
        return report.sudo()

    def _generate_and_attach_authorization_report(self):
        self.ensure_one()
        report = self._get_authorization_report()

        # Si el reporte está configurado con attachment_use, Odoo reutiliza/crea adjunto solo.
        # Igual generamos para forzar la creación si aún no existe.
        pdf_bytes, dummy_content_type = report._render_qweb_pdf(report, res_ids=[self.id])

        # Nombre consistente con el <field name="attachment"> del XML
        filename = "Autorizacion Cargo - %s.pdf" % (self.partner_id.name or self.name)

        # Evitar duplicar si ya existe
        Attachment = self.env['ir.attachment'].sudo()
        existing = Attachment.search([
            ('res_model', '=', 'sale.order'),
            ('res_id', '=', self.id),
            ('name', '=', filename),
            ('mimetype', '=', 'application/pdf'),
        ], limit=1)
        if existing:
            return existing

        return Attachment.create({
            'name': filename,
            'res_model': 'sale.order',
            'res_id': self.id,
            'type': 'binary',
            'datas': base64.b64encode(pdf_bytes),
            'mimetype': 'application/pdf',
        })
    
    def bloquear_usuario(self):
        print("Usuario bloqueado")

    # NOTA: la integración con FaceID (método sync_faceid, botón en el formulario y
    # cliente ISAPI) vive ahora en el módulo gym_faceid_control, que depende de este.
    # Aquí solo se conservan los campos de credenciales en res.branch (face_id_url,
    # face_id_user, face_id_password) que ese módulo consume.

    def pause_subscription(self):
        self.ensure_one()
        # tambien se puede pausar ventas de 1 mes
        #if self.subscription_state != '3_progress': 
        #    raise UserError('Solo se puede pausar una suscripción en estado "En Progreso".')
        
        return {
            'name': 'Pausar suscripción',
            'type': 'ir.actions.act_window',
            'res_model': 'hfit.pause.subscription.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': self.id},
        }
    
    def action_open_pause_wizard(self):
        """Abrir el wizard para pausar la suscripción de esta orden."""
        self.ensure_one()
        # tambien se puede pausar ventas de 1 mes
        #if self.subscription_state != '3_progress': 
        #    raise UserError('Solo se puede pausar una suscripción en estado "En Progreso".')
        
        return {
            'name': 'Pausar suscripción',
            'type': 'ir.actions.act_window',
            'res_model': 'hfit.pause.subscription.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': self.id},
        }
    
    def resume_subscription(self):
        # si la fecha de pausa esta en el futuro se debe ajustar la fecha de proxima factura
        # digamso q la fecha de inicio era 3 de Julio , las fechas de facturacion son los 3 de cada mes
        # la ultima fecha de factura fue 3 de octubre 
        #  la fecha pausa es del 10 al 15 de octubre entonces la siguiente factura debe ser el 8 nov
        # si reanudo el 13 de octubre , la uultima factura  + los dias de pausa - dias entre fin de pausa y reanudacion
        # ej.  3 de octubre + 5 dias de pausa - 2 dias entre fin de pausa y reanudacion = 6 de noviembre

        dias_pausa = 0
        for so in self:
            if so.pause_start_date and so.pause_end_date:
                dias_pausa = (so.pause_end_date - so.pause_start_date).days + 1
                if so.next_invoice_date:
                    # Si la reanudación es antes del fin de la pausa, ajustar la próxima factura
                    hoy = fields.Date.context_today(so)
                    if hoy < so.pause_end_date:
                        dias_antes_reanudacion = (so.pause_end_date - hoy).days
                        so.next_invoice_date += timedelta(days=dias_pausa - dias_antes_reanudacion)
                    else:
                        so.next_invoice_date += timedelta(days=dias_pausa)
                # Limpiar las fechas de pausa
                so.pause_start_date = False
                so.pause_end_date = False

        self.filtered(lambda so: so.subscription_state == '4_paused').write({'subscription_state': '3_progress'})

    def _cron_resume_paused_subscriptions(self):
        """Cron diario: reactiva automáticamente las suscripciones cuya pausa
        terminó ayer (pause_end_date = ayer), reutilizando resume_subscription()."""
        today = fields.Date.context_today(self)
        yesterday = today - relativedelta(days=1)
        _logger.info(
            "_cron_resume_paused_subscriptions: inicio. fecha_actual=%s, pause_end_date_buscado=%s",
            today, yesterday,
        )

        orders = self.search([
            ('subscription_state', '=', '4_paused'),
            ('pause_end_date', '=', yesterday),
        ])
        _logger.info("_cron_resume_paused_subscriptions: %s orden(es) encontrada(s)", len(orders))

        resumed = 0
        errors = 0
        for order in orders:
            _logger.info(
                "_cron_resume_paused_subscriptions: procesando sale.order id=%s name=%s partner=%s",
                order.id, order.name, order.partner_id.display_name,
            )
            try:
                with self.env.cr.savepoint():
                    order.resume_subscription()
                resumed += 1
                _logger.info("_cron_resume_paused_subscriptions: sale.order id=%s reactivada correctamente", order.id)
            except Exception:
                errors += 1
                _logger.exception("_cron_resume_paused_subscriptions: error al reactivar sale.order id=%s", order.id)

        _logger.info(
            "_cron_resume_paused_subscriptions: fin. encontradas=%s, reactivadas=%s, errores=%s",
            len(orders), resumed, errors,
        )

    def _process_auto_invoice(self, invoice):
        """
        Sobreescribimos este método para evitar que Odoo intente validar (post)
        y cobrar la factura automáticamente.
        Al hacer 'pass', la factura se queda en estado Borrador tal como fue creada.
        """
        _logger.info(f"SKIP: Se evitó el posteo automático de la factura {invoice.id} para la suscripción {self.name}")
        pass  # No llamamos a super(), por lo tanto no hace action_post ni cobro.

    def _handle_unpaid_subscriptions(self):
        """
        El cron llama a este método para saber qué suscripciones cerrar por impago.
        Al devolver un diccionario vacío, engañamos al cron para que crea
        que no hay ninguna suscripción pendiente de cierre por falta de pago.
        """
        return {}

    def _prepare_upsell_renew_order_values(self, subscription_state):
        """
        Extiende el dict de valores para la nueva orden de renovación/upsell
        añadiendo los campos de tarjeta de crédito cuando se trata de una
        renovación (subscription_state == '2_renewal').

        Solo se copian los campos si existen en el modelo (defensive check),
        por lo que este override es seguro aunque hfit no esté instalado en
        otro entorno.

        Nota de seguridad: cc_number_stored contiene el número completo de
        tarjeta tal como lo guarda hfit actualmente. Si en el futuro se
        decide no propagar cc_number, bastaría con removerlo de CC_FIELDS.
        """
        values = super()._prepare_upsell_renew_order_values(subscription_state)

        if subscription_state != '2_renewal':
            return values

        # Campos a propagar en la orden de renovación.
        # cc_number_stored se asigna directo (campo almacenado); NO usar
        # cc_number_input aquí porque es store=False y create() no dispara
        # su inverse de forma fiable.
        CC_FIELDS = {
            'cc_brand_id': self.cc_brand_id.id if self.cc_brand_id else False,
            'cc_cardholdername': self.cc_cardholdername or False,
            'expiration_date': self.expiration_date or False,
            'cc_number': self.cc_number_stored or False,
            'cc_number_stored': self.cc_number_stored or False,
        }

        # Sólo asignamos los campos que realmente existen en el modelo
        # (evita crash si hfit no está activo en otro entorno de la misma DB)
        model_fields = self._fields
        for field_name, field_value in CC_FIELDS.items():
            if field_name in model_fields:
                values[field_name] = field_value

        # La nueva orden de renovación arranca sin líneas; el vendedor
        # las agrega manualmente antes de confirmar.
        values['order_line'] = []

        return values

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.onchange('product_id')
    def _onchange_product_subscription_check(self):
        """
        Lanza una advertencia si se selecciona el producto 'pb3600'
        y el cliente no tiene suscripciones previas.
        """

        PRODUCT_CODE_TO_CHECK = 'ph3600'

        # Si el producto seleccionado no es el que buscamos, no hacer nada
        if not self.product_id or self.product_id.default_code != PRODUCT_CODE_TO_CHECK:
            return {}

        if self.order_id.partner_id:            
            warning_title = "¡Producto Requiere suscripcion Previa!"
            warning_message = "El producto '%s' requiere que el cliente '%s' ya tenga una suscripción anterior." % (self.product_id.name, self.order_id.partner_id.name)
            
            return {
                'warning': {
                    'title': warning_title,
                    'message': warning_message,
                }
            }
    
        # Si no hay cliente o el cliente sí tiene suscripciones, no hacer nada
        return {}

