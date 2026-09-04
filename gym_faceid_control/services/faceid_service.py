# -*- coding: utf-8 -*-
import logging
from .faceid_isapi_client import FaceIdIsapiClient
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class FaceIdService:
    """
    Service Layer para FaceID. 
    Encapsula la lógica de integración con ISAPI, asegurando idempotencia
    y manejando la generación centralizada de logs para trazabilidad.
    """
    def __init__(self, env):
        self.env = env

    def _get_client(self, branch):
        if not branch or not branch.face_id_url:
            raise UserError("La sucursal no tiene configurada la URL o credenciales de FaceID.")
        return FaceIdIsapiClient(
            base_url=branch.face_id_url,
            username=branch.face_id_user,
            password=branch.face_id_password
        )

    def _get_partner(self, identifier):
        if not identifier:
            return self.env['res.partner']
        return self.env['res.partner'].search([('id_biometrico', '=', identifier)], limit=1)

    def _log_action(self, action, branch, partner, res, order=None):
        """Helper para registrar la respuesta en el historial de Odoo (gym.faceid.log)."""
        text_val = str(res.get('text', '') if res else '')
        payload_val = str(res.get('payload', '') if res else '')
        log_vals = {
            'action': action,
            'status_code': str(res.get('status_code', '')),
            'response_text': text_val[:500],
            'payload': payload_val,
            'branch_id': branch.id if branch else False,
            'partner_id': partner.id if partner else False,
            'state': 'ok' if res.get('ok') else 'error'
        }
        if order:
            log_vals['sale_order_id'] = order.id

        # sudo() para asegurar que la escritura del log no falle por permisos de lectura
        return self.env['gym.faceid.log'].sudo().create(log_vals)

    def search_user(self, branch, identifier, order=None) -> dict:
        """Busca un usuario en FaceID por su ID Biométrico."""
        client = self._get_client(branch)
        res = client.search_user(identifier)
        partner = self._get_partner(identifier)
        self._log_action('search', branch, partner, res, order)
        return res

    def create_user(self, branch, partner, begin, end, order=None) -> dict:
        """Crea un nuevo usuario en FaceID y lo habilita con las fechas de acceso."""
        client = self._get_client(branch)
        identifier = str(partner.id_biometrico).strip() if partner.id_biometrico else ''
        if not identifier:
            raise UserError(f"El cliente {partner.name} no tiene un ID Biométrico configurado.")

        res = client.create_user(
            employee_no=identifier,
            name=partner.name,
            enable=True,
            begin_time=begin,
            end_time=end,
            branch_id=branch.id
        )
        self._log_action('record', branch, partner, res, order)
        return res

    def activate_user(self, branch, identifier, begin, end, order=None) -> dict:
        """Actualiza y habilita un usuario existente con nuevas fechas."""
        client = self._get_client(branch)
        partner = self._get_partner(identifier)
        res = client.modify_user(
            employee_no=identifier,
            enable=True,
            begin_time=begin,
            end_time=end,
            branch_id=branch.id
        )
        self._log_action('modify', branch, partner, res, order)
        return res

    def deactivate_user(self, branch, identifier, order=None) -> dict:
        """Deshabilita un usuario existente sin modificar sus fechas (ej. fin de suscripción)."""
        client = self._get_client(branch)
        partner = self._get_partner(identifier)
        res = client.modify_user(
            employee_no=identifier,
            enable=False,
            branch_id=branch.id
        )
        self._log_action('modify', branch, partner, res, order)
        return res

    def expire_user(self, branch, identifier, end_date, order=None) -> dict:
        """Mantiene habilitado al usuario pero ajusta su endTime para que el dispositivo
        le siga permitiendo el ingreso hasta esa fecha y luego lo bloquee automáticamente.
        Se usa en bajas de suscripción: se respeta el período ya pagado en lugar de
        cortar el acceso de inmediato."""
        client = self._get_client(branch)
        partner = self._get_partner(identifier)
        res = client.modify_user(
            employee_no=identifier,
            enable=True,
            end_time=end_date,
            branch_id=branch.id
        )
        self._log_action('modify', branch, partner, res, order)
        return res

    def pause_user(self, branch, identifier, begin, end, order=None) -> dict:
        """Pausa un usuario existente (lo deshabilita temporalmente pero actualiza sus fechas si es necesario)."""
        client = self._get_client(branch)
        partner = self._get_partner(identifier)
        res = client.modify_user(
            employee_no=identifier,
            enable=False,
            branch_id=branch.id
        )
        self._log_action('modify', branch, partner, res, order)
        return res

    def resume_user(self, branch, identifier, begin, end, order=None) -> dict:
        """Reanuda un usuario existente (lo vuelve a habilitar con las fechas vigentes)."""
        client = self._get_client(branch)
        partner = self._get_partner(identifier)
        res = client.modify_user(
            employee_no=identifier,
            enable=True,
            begin_time=begin,
            end_time=end,
            branch_id=branch.id
        )
        self._log_action('modify', branch, partner, res, order)
        return res
