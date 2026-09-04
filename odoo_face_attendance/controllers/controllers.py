import io
import json
import base64
import uuid
import pytz
from urllib.parse import quote
import numpy as np
import face_recognition
from odoo import http, fields
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class FaceAttendance(http.Controller):

    # 1. RUTA PRINCIPAL: Muestra la cámara
    @http.route('/face_attendance', type='http', auth='public', csrf=False)
    def face_attendance(self, **kwargs):
        unique_req_id = str(uuid.uuid4())
        branch = kwargs.get('branch', '')
        branch_label = f' - Sucursal {branch}' if branch else ''

        return f"""<!DOCTYPE html>
    <html>
    <head>
        <title>Face Attendance</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
        <meta http-equiv="Pragma" content="no-cache" />
        <meta http-equiv="Expires" content="0" />
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; text-align: center; background-color: #f2f2f2; }}
            .container {{ max-width: 600px; margin: 5% auto; padding: 20px; border-radius: 8px; background: #fff; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            video, canvas {{ width: 100%; border-radius: 8px; border: 1px solid #ccc; }}
            button, .btn-submit {{ margin-top: 15px; padding: 12px 24px; font-size: 16px; border: none; background-color: #71639e; color: white; border-radius: 5px; cursor: pointer; }}
            #submit_photo {{ display: none; background-color: #28a745; }}
            .loading {{ display: none; color: #71639e; font-weight: bold; margin-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h3>Registro de Asistencia{branch_label}</h3>
            <video id="video" autoplay playsinline></video>
            <canvas id="canvas" style="display: none;"></canvas>

            <button id="snap" type="button">Capturar Foto</button>

            <form id="uploadForm" action="/submit_face" method="post">
                <input type="hidden" name="req_token" value="{unique_req_id}">
                <input type="hidden" name="face_image" id="face_image_input">
                <input type="hidden" name="branch" value="{branch}">
                <input type="submit" id="submit_photo" class="btn-submit" value="Confirmar y Enviar">
            </form>
            <p id="msg_procesando" class="loading">Procesando... espere un momento.</p>
        </div>

        <script>
            const video = document.getElementById('video');
            const canvas = document.getElementById('canvas');
            const snapBtn = document.getElementById('snap');
            const submitBtn = document.getElementById('submit_photo');
            const faceInput = document.getElementById('face_image_input');
            const form = document.getElementById('uploadForm');

            navigator.mediaDevices.getUserMedia({{ video: true }})
                .then(stream => {{ video.srcObject = stream; }})
                .catch(err => {{ alert("Error de cámara: " + err); }});

            snapBtn.addEventListener('click', () => {{
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                canvas.getContext('2d').drawImage(video, 0, 0);
                faceInput.value = canvas.toDataURL('image/jpeg', 0.8);
                video.style.display = 'none';
                canvas.style.display = 'block';
                snapBtn.style.display = 'none';
                submitBtn.style.display = 'block';
            }});

            form.addEventListener('submit', (e) => {{
                submitBtn.disabled = true;
                submitBtn.value = "Enviando...";
                document.getElementById('msg_procesando').style.display = 'block';
                setTimeout(() => {{ faceInput.value = ""; }}, 100);
            }});

            window.addEventListener('pageshow', (event) => {{
                if (event.persisted || (performance.navigation.type === 2)) {{
                    window.location.reload();
                }}
            }});
        </script>
    </body>
    </html>"""

    # 2. RUTA DE PROCESAMIENTO (POST)
    @http.route('/submit_face', type='http', auth='public', csrf=False, methods=['POST'])
    def submit_face(self, **kwargs):
        data_url = kwargs.get('face_image')
        branch_raw = kwargs.get('branch', '0')

        try:
            branch_id = int(branch_raw) if branch_raw else 0
        except (ValueError, TypeError):
            branch_id = 0

        if not data_url or not data_url.startswith('data:image'):
            return request.redirect('/face_attendance/result?status=error&msg=No se recibio imagen')

        try:
            header, encoded = data_url.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            image = face_recognition.load_image_file(io.BytesIO(image_bytes))
            encodings = face_recognition.face_encodings(image)

            if not encodings:
                return request.redirect('/face_attendance/result?status=warning&msg=Rostro no detectado')

            input_encoding = encodings[0]
            employees = request.env['hr.employee'].sudo().search([('face_encoding', '!=', False)])

            for emp in employees:
                emp_encoding = json.loads(emp.face_encoding)
                match = face_recognition.compare_faces([np.array(emp_encoding)], input_encoding, tolerance=0.5)

                if match[0]:
                    Attendance = request.env['hr.attendance'].sudo()
                    now = fields.Datetime.now()

                    # Buscar sesión abierta del empleado (sin checkout)
                    open_att = Attendance.search(
                        [('employee_id', '=', emp.id), ('check_out', '=', False)],
                        order='check_in desc', limit=1
                    )

                    if open_att:
                        open_branch = open_att.branch_id or 0

                        if open_branch != branch_id:
                            # Sesión abierta en otra sucursal → cerrar y abrir nueva
                            _logger.info(
                                f"Empleado {emp.name}: cambio de sucursal {open_branch} → {branch_id}"
                            )
                            open_att.write({
                                'check_out': now,
                                'close_reason': f'Cambio de sucursal: {open_branch} → {branch_id}',
                            })
                            Attendance.create({
                                'employee_id': emp.id,
                                'check_in': now,
                                'branch_id': branch_id,
                            })
                            status_txt = f"Entrada sucursal {branch_id} (sesión sucursal {open_branch} cerrada automáticamente)"
                        else:
                            # Misma sucursal → checkout normal
                            open_att.write({'check_out': now})
                            status_txt = f"Salida sucursal {branch_id}"
                    else:
                        # Sin sesión abierta → nuevo checkin
                        Attendance.create({
                            'employee_id': emp.id,
                            'check_in': now,
                            'branch_id': branch_id,
                        })
                        status_txt = f"Entrada sucursal {branch_id}"

                    msg_encoded = quote(f"{emp.name} - {status_txt}")
                    return request.redirect(
                        f'/face_attendance/result?status=success&msg={msg_encoded}'
                        f'&employee_id={emp.id}&branch={branch_id}'
                    )

            return request.redirect('/face_attendance/result?status=warning&msg=No se encontro coincidencia')

        except Exception as e:
            _logger.error(f"Error procesando imagen de asistencia: {e}", exc_info=True)
            return request.redirect('/face_attendance/result?status=error&msg=Error en sistema')

    # 3. RUTA DE RESULTADO
    @http.route('/face_attendance/result', type='http', auth='public', website=True)
    def face_attendance_result(self, **kwargs):
        status = kwargs.get('status', 'info')
        msg = kwargs.get('msg', 'Proceso finalizado')
        employee_id = kwargs.get('employee_id')
        branch = kwargs.get('branch', '0')

        sessions = []
        if employee_id:
            try:
                emp_id = int(employee_id)
                Attendance = request.env['hr.attendance'].sudo()
                now = fields.Datetime.now()
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

                company_tz = pytz.timezone(
                    request.env['res.users'].sudo().browse(2).tz or 'UTC'
                )

                def to_local(dt):
                    if not dt:
                        return 'Abierto'
                    return pytz.utc.localize(dt).astimezone(company_tz).strftime('%H:%M:%S')

                today_sessions = Attendance.search([
                    ('employee_id', '=', emp_id),
                    ('check_in', '>=', today_start),
                    ('check_in', '<=', today_end),
                ], order='check_in asc')

                for att in today_sessions:
                    sessions.append({
                        'employee': att.employee_id.name,
                        'branch': att.branch_id if att.branch_id else '-',
                        'check_in': to_local(att.check_in),
                        'check_out': to_local(att.check_out),
                    })
            except (ValueError, TypeError):
                pass

        return self._render_result(msg, status, sessions, branch)

    def _render_result(self, message, status, sessions=None, branch='0'):
        color = "#71639e"
        if status == 'success':
            color = "#28a745"
        if status == 'warning':
            color = "#ffc107"
        if status == 'error':
            color = "#dc3545"

        branch_link = f"/face_attendance?branch={branch}" if branch and branch != '0' else "/face_attendance"

        sessions_html = ""
        if sessions:
            rows = ""
            for s in sessions:
                checkout_style = 'color:#28a745;font-weight:bold;' if s['check_out'] == 'Abierto' else ''
                rows += f"""
                <tr>
                    <td>{s['employee']}</td>
                    <td>{s['branch']}</td>
                    <td>{s['check_in']}</td>
                    <td style="{checkout_style}">{s['check_out']}</td>
                </tr>"""
            sessions_html = f"""
            <div style="margin-top:24px;overflow-x:auto;">
                <h4 style="color:#555;margin-bottom:10px;">Sesiones del día</h4>
                <table style="width:100%;border-collapse:collapse;font-size:0.9em;">
                    <thead>
                        <tr style="background:#71639e;color:white;">
                            <th style="padding:8px 12px;text-align:left;">Empleado</th>
                            <th style="padding:8px 12px;text-align:left;">Sucursal</th>
                            <th style="padding:8px 12px;text-align:left;">Entrada</th>
                            <th style="padding:8px 12px;text-align:left;">Salida</th>
                        </tr>
                    </thead>
                    <tbody>{rows}
                    </tbody>
                </table>
            </div>"""

        content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Resultado</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: Arial, sans-serif; background-color: #f9f9f9; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }}
                .message-box {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); text-align: center; max-width: 720px; width: 100%; }}
                .message {{ font-size: 1.4em; color: {color}; margin-bottom: 20px; }}
                .btn {{ text-decoration: none; background: #71639e; color: white; padding: 10px 20px; border-radius: 5px; display: inline-block; margin-top: 20px; }}
                table tr:nth-child(even) {{ background: #f5f5f5; }}
                table td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #e0e0e0; }}
            </style>
        </head>
        <body>
            <div class="message-box">
                <p class="message">{message}</p>
                {sessions_html}
                <a href="{branch_link}" class="btn">Volver a Marcar</a>
            </div>
            <script>
                setTimeout(() => {{ window.location.href = "{branch_link}"; }}, 15000);
            </script>
        </body>
        </html>
        """
        return request.make_response(content, [('Cache-Control', 'no-store')])
