from odoo import fields, models, api
import face_recognition
import base64
import io
from PIL import Image
import numpy as np
import json


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
            if record.image_1920:
                img_data = record.image_1920
                try:
                    image = Image.open(io.BytesIO(base64.b64decode(img_data))) or None
                    image_np = np.array(image)

                    # Get encoding
                    face_locations = face_recognition.face_locations(image_np)

                    if not face_locations:
                        raise ValueError("No face found in the image.")

                    # Encode face from the first detected face
                    face_encoding = face_recognition.face_encodings(image_np, known_face_locations=face_locations)[0]
                    record.face_encoding = json.dumps(face_encoding.tolist())
                except Exception as e:
                    record.face_encoding = None
                # record.face_encoding = face_encoding
            
             


    
