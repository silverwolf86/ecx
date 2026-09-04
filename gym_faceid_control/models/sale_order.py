import logging

from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    faceid_sync_state = fields.Selection([
        ('pending', 'Pendiente de Sincronización'),
        ('active', 'Sincronizado (Activo)'),
        ('blocked', 'Sincronizado (Bloqueado)'),
        ('error', 'Error de Sincronización')
    ], string='Estado Sincronización FaceID', default='pending', tracking=True, copy=False)

    faceid_last_sync = fields.Datetime(string='Última Sincronización FaceID', copy=False, readonly=True)
    faceid_last_error = fields.Text(string='Último Error FaceID', copy=False, readonly=True)

    def _get_faceid_employee_no(self):
        """ Retorna el employeeNo (ID Biométrico) del cliente sanitizado.
        FaceID SIEMPRE debe identificar al cliente por id_biometrico, nunca por vat. """
        self.ensure_one()
        if not self.partner_id.id_biometrico:
            return self.partner_id.vat.strip() if self.partner_id.vat else None
        return str(self.partner_id.id_biometrico).strip()

    def _calculate_faceid_validity_dates(self):
        """
        Calcula begin_time y end_time.
        Caso 1: Suscripción recurrente (1 año desde start_date por Odoo base).
        Caso 2: Producto temporal (start_date + duración FaceID en producto).
        """
        self.ensure_one()
        
        # Fecha de inicio por defecto: start_date de hfit o date_order de odoo
        # Si existe start_date (de hfit)
        if hasattr(self, 'start_date') and self.start_date:
            begin_date = self.start_date
        else:
            begin_date = self.date_order.date() if self.date_order else fields.Date.today()
            
        end_date = begin_date  # init
        
        is_recurring = False
        if hasattr(self, '_has_recurring_product'):
            is_recurring = self._has_recurring_product()
        elif hasattr(self, 'is_subscription'):
            is_recurring = self.is_subscription
            
        if is_recurring:
            # Caso 1: Suscripción
            end_date = begin_date + relativedelta(years=1)
        else:
            # Caso 2: Duración no recurrente
            max_days = 0
            for line in self.order_line:
                product = line.product_template_id
                if product.faceid_access_duration_value and product.faceid_access_duration_unit:
                    val = product.faceid_access_duration_value
                    unit = product.faceid_access_duration_unit
                    
                    if unit == 'days':
                        test_end = begin_date + relativedelta(days=val)
                    elif unit == 'weeks':
                        test_end = begin_date + relativedelta(weeks=val)
                    elif unit == 'months':
                        test_end = begin_date + relativedelta(months=val)
                    elif unit == 'years':
                        test_end = begin_date + relativedelta(years=val)
                    else:
                        test_end = begin_date
                        
                    delta_days = (test_end - begin_date).days
                    if delta_days > max_days:
                        max_days = delta_days
                        end_date = test_end
                        
            # Si ninguna linea sumó días, le damos 1 día por defecto o lo que se prefiera
            if end_date == begin_date:
                end_date = begin_date + relativedelta(days=1)

        begin_time_str = f"{begin_date.strftime('%Y-%m-%d')}T00:00:00"
        end_time_str = f"{end_date.strftime('%Y-%m-%d')}T23:59:59"

        return begin_time_str, end_time_str


    # =========================================================================
    # CAPA DE DOMINIO - MÉTODOS SEMÁNTICOS FACEID
    # =========================================================================

    def _get_faceid_service(self):
        from ..services.faceid_service import FaceIdService
        return FaceIdService(self.env)

    def _faceid_check_exists(self, branch, identifier, order=None):
        """Consulta ISAPI (Caso A) para saber si el identificador ya existe en FaceID."""
        service = self._get_faceid_service()
        search = service.search_user(branch, identifier, order)
        user_info_search = (search.get('json') or {}).get('UserInfoSearch', {}) if search.get('ok') else {}
        return bool(user_info_search.get('numOfMatches', 0))

    def _faceid_update_state(self, res, enable=True):
        """Actualiza el estado de sincronización en función de la respuesta de ISAPI"""
        success = res.get('ok', False)
        error_msg = res.get('text') if not success else False
        self.write({
            'faceid_sync_state': ('active' if enable else 'blocked') if success else 'error',
            'faceid_last_error': error_msg,
            'faceid_last_sync': fields.Datetime.now()
        })

    def faceid_sync_on_confirm(self):
        """Flujo: Alta o actualización al confirmar venta/suscripción."""
        service = self._get_faceid_service()
        for order in self:
            if not order.branch_id or not order.branch_id.face_id_url:
                continue
            begin, end = order._calculate_faceid_validity_dates()
            identifier = order._get_faceid_employee_no()
            if not identifier:
                order._faceid_update_state({'ok': False, 'text': 'Sin ID Biométrico'}, enable=False)
                continue

            # 1. Busco si existe
            if order._faceid_check_exists(order.branch_id, identifier, order):
                # Existe -> Modifico
                res = service.activate_user(order.branch_id, identifier, begin, end, order)
            else:
                # No existe -> Creo
                res = service.create_user(order.branch_id, order.partner_id, begin, end, order)

            order._faceid_update_state(res, enable=True)

    def faceid_activate_member(self):
        """Alias explícito para altas manuales o reprocesos."""
        self.faceid_sync_on_confirm()

    def faceid_deactivate_member(self, until_date=None):
        """Baja del usuario. Si se indica `until_date`, el usuario se mantiene habilitado
        en FaceID y el dispositivo corta el acceso automáticamente al llegar esa fecha
        (se respeta el período ya pagado, ej. baja de suscripción). Si no se indica,
        se bloquea de inmediato (ej. bloqueo manual o pago fallido)."""
        service = self._get_faceid_service()
        for order in self:
            if not order.branch_id or not order.branch_id.face_id_url:
                continue
            identifier = order._get_faceid_employee_no()
            if not identifier:
                continue
            if until_date:
                end_time = f"{until_date.strftime('%Y-%m-%d')}T23:59:59"
                res = service.expire_user(order.branch_id, identifier, end_time, order)
                order._faceid_update_state(res, enable=True)
            else:
                res = service.deactivate_user(order.branch_id, identifier, order)
                order._faceid_update_state(res, enable=False)

    def bloquear_usuario(self):
        res = super().bloquear_usuario()
        self.faceid_deactivate_member()


    def faceid_pause_member(self):
        """Pausa temporal de membresía (congelamiento)."""
        service = self._get_faceid_service()
        for order in self:
            if not order.branch_id or not order.branch_id.face_id_url:
                continue
            begin, end = order._calculate_faceid_validity_dates()
            identifier = order._get_faceid_employee_no()
            if identifier:
                res = service.pause_user(order.branch_id, identifier, begin, end, order)
                order._faceid_update_state(res, enable=False)

    def faceid_resume_member(self):
        """Reanudación de membresía tras una pausa."""
        service = self._get_faceid_service()
        for order in self:
            if not order.branch_id or not order.branch_id.face_id_url:
                continue
            begin, end = order._calculate_faceid_validity_dates()
            identifier = order._get_faceid_employee_no()
            if identifier:
                res = service.resume_user(order.branch_id, identifier, begin, end, order)
                order._faceid_update_state(res, enable=True)

    def faceid_mark_payment_failed(self):
        """Bloqueo de acceso por mora/pago fallido."""
        service = self._get_faceid_service()
        for order in self:
            if not order.branch_id or not order.branch_id.face_id_url:
                continue
            identifier = order._get_faceid_employee_no()
            if identifier:
                # Un pago fallido es equivalente a desactivar temporalmente
                res = service.deactivate_user(order.branch_id, identifier, order)
                order._faceid_update_state(res, enable=False)

    def faceid_reactivate_member(self):
        """Reactivación tras normalizar pagos."""
        self.faceid_resume_member()

    # =========================================================================
    # sync_faceid - Reglas exactas de bloqueo/sincronización
    # =========================================================================

    def _faceid_partner_has_failed_invoice(self):
        """Factura fallida = state == 'draft' AND estado_cobro == 'fallido' (regla exacta)."""
        self.ensure_one()
        return bool(self.env['account.move'].sudo().search_count([
            ('partner_id', '=', self.partner_id.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'draft'),
            ('estado_cobro', '=', 'fallido'),
        ]))

    def _faceid_partner_has_subscription_state(self, states):
        """True si alguna suscripción del cliente tiene subscription_state en `states`."""
        self.ensure_one()
        return bool(self.env['sale.order'].sudo().search_count([
            ('partner_id', '=', self.partner_id.id),
            ('is_subscription', '=', True),
            ('subscription_state', 'in', states),
        ]))

    def sync_faceid(self):
        """
        Sincroniza el cliente de esta orden con FaceID, identificándolo SIEMPRE por
        partner.id_biometrico (nunca por vat), y aplicando en este orden de prioridad:

          1. Factura fallida (state=draft AND estado_cobro=fallido) -> bloquear
          2. Cliente dado de baja (subscription_state=6_churn)      -> bloquear
          3. Cliente pausado (subscription_state=4_paused)          -> bloquear
          4. Cliente no existe en FaceID                            -> sincronizar/crear
          5. Cliente ya existe en FaceID                            -> mantener comportamiento actual

        Reutiliza los métodos ya existentes (faceid_deactivate_member, faceid_sync_on_confirm,
        _faceid_check_exists) sin duplicar llamadas ISAPI.
        """
        self.ensure_one()

        if self._faceid_partner_has_failed_invoice():
            _logger.info(
                "sync_faceid order %s: factura fallida (state=draft, estado_cobro=fallido) para %s, bloqueando en FaceID",
                self.id, self.partner_id.display_name,
            )
            self.faceid_deactivate_member()
            return True

        if self._faceid_partner_has_subscription_state(('6_churn',)):
            _logger.info(
                "sync_faceid order %s: cliente %s dado de baja (subscription_state=6_churn), bloqueando en FaceID",
                self.id, self.partner_id.display_name,
            )
            self.faceid_deactivate_member()
            return True

        if self._faceid_partner_has_subscription_state(('4_paused',)):
            _logger.info(
                "sync_faceid order %s: cliente %s pausado (subscription_state=4_paused), bloqueando en FaceID",
                self.id, self.partner_id.display_name,
            )
            self.faceid_deactivate_member()
            return True

        if not self.branch_id or not self.branch_id.face_id_url:
            raise UserError("La sucursal no tiene configurada la integración FaceID.")

        identifier = self._get_faceid_employee_no()
        if not identifier:
            raise UserError(f"El cliente {self.partner_id.name} no tiene un ID Biométrico configurado.")

        if not self._faceid_check_exists(self.branch_id, identifier, self):
            _logger.info(
                "sync_faceid order %s: cliente %s no existe en FaceID, sincronizando",
                self.id, self.partner_id.display_name,
            )
            self.faceid_sync_on_confirm()
        # Si ya existe en FaceID y no aplica ninguna condición de bloqueo,
        # se mantiene el comportamiento actual (sin acciones adicionales).
        return True
