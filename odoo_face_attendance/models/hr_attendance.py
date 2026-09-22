import base64
import io
import json
import logging

import face_recognition
import numpy as np
from PIL import Image

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    branch_id = fields.Integer(string='Sucursal ID')
    close_reason = fields.Char(string='Razón de Cierre')


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    face_encoding = fields.Text(string='Face Encoding', help="Base64 encoded face encoding data for attendance verification.", compute='_compute_face_encoding', store=True)

    @api.depends('image_1920')
    def _compute_face_encoding(self):
        for record in self:
            record.face_encoding = False
            if not record.image_1920:
                continue
            try:
                # face_recognition requiere RGB de 8 bits (PNG con alfa, escala de grises, etc. fallan)
                image = Image.open(io.BytesIO(base64.b64decode(record.image_1920))).convert('RGB')
                image_np = np.array(image)

                face_locations = face_recognition.face_locations(image_np)
                if not face_locations:
                    _logger.info("Empleado %s: no se detectó rostro en la foto", record.display_name)
                    continue

                # Encode face from the first detected face
                face_encoding = face_recognition.face_encodings(image_np, known_face_locations=face_locations)[0]
                record.face_encoding = json.dumps(face_encoding.tolist())
            except Exception:
                # p.ej. avatar SVG autogenerado por Odoo cuando el empleado no tiene foto
                _logger.info("Empleado %s: no se pudo generar el face encoding", record.display_name, exc_info=True)
