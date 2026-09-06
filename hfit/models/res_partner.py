from odoo import models, fields, api
import requests

#api_url = "https://api.virtuagym.com/api/v1/club/{club_id}/member"
#api_key = "l9tLmF7nyKrCK16LmVN9KL9pQaLyhNbRgZWahysz3p"
#club_id = "27207"
#club_secret = "CS-27207-ACCESS-DwvSshlMSoZGHT2Y9UEJZr6b1"
#api_url = api_url.format(club_id=club_id)

import logging

_logger = logging.getLogger(__name__)

VIRTUAGYM_SECRET_KEYS = ('api_key', 'club_secret')


def _sanitize_virtuagym_payload(payload):
    """Devuelve una copia (recursiva) del payload/params enviado a Virtuagym
    enmascarando credenciales (api_key, club_secret) antes de guardarlo en el
    log de auditoría."""
    if isinstance(payload, dict):
        return {
            key: ('***' if key in VIRTUAGYM_SECRET_KEYS and value else _sanitize_virtuagym_payload(value))
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [_sanitize_virtuagym_payload(item) for item in payload]
    return payload


class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    member_id = fields.Char('member_id', tracking=True)

    id_biometrico = fields.Char(
        string="ID Biométrico",
        copy=False,
        index=True,
        tracking=True,
        help="Identificador utilizado exclusivamente para la integración con FaceID. "
             "Se inicializa a partir del VAT al crear el cliente, pero es independiente del mismo.",
    )
    gender = fields.Selection([
        ('m', 'Masculino'),
        ('f','Femenino'),
        ('o', 'No especificado')
        ], string='Genero')
    
    birthday = fields.Date('birthday', required=False)

    cc_brand_id = fields.Many2one(comodel_name='credit.card.brand', string='Marca Tarjeta')

    cc_cardholdername = fields.Char(string='Nombre Tarjetahabiente',required=False)
    expiration_date = fields.Date(string='Fecha Expiracion Tarjeta',required=False)
    cc_number = fields.Char(string='Tarjeta',required=False)

    member_branch_id = fields.Many2one(comodel_name='res.branch', string='Sucursal', 
                                       required=False)
    
    is_agree_terms = fields.Boolean(string='Estoy de Acuerdo', default=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('id_biometrico') and vals.get('vat'):
                vals['id_biometrico'] = vals['vat']
        return super().create(vals_list)

    def _log_virtuagym_action(self, action, branch, request_url, payload, response=None, sale_order=None, error=None):
        """Registra en virtuagym.log la trama enviada a Virtuagym (y su respuesta) para
        poder revisarla después. Enmascara credenciales antes de guardar el payload."""
        if response is not None:
            status_code = response.status_code
            response_text = response.text
            state = 'ok' if response.status_code == 200 else 'error'
        else:
            status_code = False
            response_text = error
            state = 'error'

        self.env['virtuagym.log'].sudo().create({
            'action': action,
            'branch_id': branch.id if branch else False,
            'partner_id': self.id if self else False,
            'sale_order_id': sale_order.id if sale_order else False,
            'request_url': request_url,
            'payload': str(_sanitize_virtuagym_payload(payload)),
            'status_code': str(status_code) if status_code else False,
            'response_text': (response_text or '')[:2000],
            'state': state,
        })

    def check_virtuagym_member(self, email=None, vat= None, branch=None):

        if branch.virtuagym_api_key:
            api_key = branch.virtuagym_api_key
            api_url = "https://api.virtuagym.com/api/v1/club/{club_id}/member"
            club_secret = branch.virtuagym_club_secret
            club_id = branch.virtuagym_club_id
            api_url = api_url.format(club_id=club_id)
        else:
            return False, None, "La sucursal no tiene configurada la API Key de VirtuaGym"        

        headers = {
            "api_key": api_key,
            "Content-Type": "application/json",
        }
        params = {
            "api_key": api_key,
            "club_secret": club_secret,
            
        }
        if email:
            params['email'] = email
        if vat:
            params['club_member_id'] = vat  

        # Make the API request
        response = requests.get(api_url, headers=headers, params=params)
        self._log_virtuagym_action('check', branch, api_url, params, response=response)

        if response.status_code == 200:
            data = response.json()
            if data.get("result"):
                return True, data["result"][0], None  # Return member data if found
        return False, None, None  # Member not found
    
    def sync_virtuagym_member(self, branch):
        if not self.vat:
            return None
        exists, member_data, msg1 = self.check_virtuagym_member(vat=self.vat, branch=branch)
        if not exists:
            _logger.info("No existe el miembro en VirtuaGym, se procede a crearlo")
            is_created, vg_member_id, msg = self.create_virtuagym_member(None, self, branch)
            if is_created:
                self.member_id = vg_member_id
        else:
            _logger.info("El miembro ya existe en VirtuaGym, se procede a actualizarlo")
            vals = {}
            vals['vat'] = self.vat
            vals['email'] = self.email
            vals['firstname'] = self.firstname
            vals['lastname'] = self.lastname
            vals['gender'] = self.gender
            vals['birthday'] = self.birthday
            # La clave 'mobile' es la que espera la API de Virtuagym; en Odoo 19
            # res.partner.mobile ya no existe y el número vive en 'phone'.
            vals['mobile'] = self.phone
            vals['street'] = self.street or ''

            vals['member_id'] = member_data.get('member_id')
            self.update_virtuagym_member(vals, branch)
    
    def create_virtuagym_member(self, vals, partner = None, branch=None):

        if branch.virtuagym_api_key:
            api_key = branch.virtuagym_api_key
            api_url = "https://api.virtuagym.com/api/v1/club/{club_id}/member"
            club_secret = branch.virtuagym_club_secret
            club_id = branch.virtuagym_club_id
            api_url = api_url.format(club_id=club_id)
        else:
            return False, None, "La sucursal no tiene configurada la API Key de VirtuaGym"
        
        headers = {
            "Content-Type": "application/json",
        }
        params = {
            "api_key": api_key,
            "club_secret": club_secret
        }

        if partner:
            vals = {}
            vals['vat'] = partner.vat
            vals['email'] = partner.email
            vals['firstname'] = partner.firstname
            vals['lastname'] = partner.lastname
            vals['gender'] = partner.gender
            vals['birthday'] = partner.birthday
            # 'mobile' = clave de la API de Virtuagym; el dato sale de partner.phone (v19)
            vals['mobile'] = partner.phone
            vals['street'] = partner.street or ''
        
      
        body = {
            "firstname": vals.get('firstname'),
            "lastname": vals.get('lastname'),
            "club_member_id": vals.get('vat'),
            "email": vals.get('email'),
            "active": True,
            "is_pro": True,
            "country": "EC",
            "mobile": vals.get('mobile'),
            "lang": "es"        ,
                "street": vals.get('street', ''),
        }

        if vals.get('gender'):
            body["gender"] = vals.get('gender')

        if vals.get('birthday'):
            body["birthday"] = str(vals.get('birthday'))

        if vals.get('member_id'):
            body['member_id'] = vals.get('member_id')

        try:
            response = requests.put(api_url, headers=headers, params=params,json=body)
            self._log_virtuagym_action('create', branch, api_url, {'params': params, 'body': body}, response=response)

            if response.status_code == 200:
                data = response.json()
                if data.get("result"):
                    return True, data["result"].get('member_id'), "OK"  # Return member data if found
            else:
                return False, None, response.json().get('statusmessage')  # error handling

        except Exception as e:
            self._log_virtuagym_action('create', branch, api_url, {'params': params, 'body': body}, error=str(e))
            return False, None, str(e)

    def create_virtuagym_membership_instance(self, branch, membership_id, start_date, payment_method, salesperson_id, sale_order=None):
        """Crea una membership instance (contrato) en Virtuagym para este socio,
        a partir de una definición de membresía (membership_id) ya existente en el club.
        """
        self.ensure_one()

        if not branch.virtuagym_api_key:
            return False, None, "La sucursal no tiene configurada la API Key de VirtuaGym"

        try:
            member_id = int(self.member_id)
        except (TypeError, ValueError):
            return False, None, "El socio no tiene un member_id válido de VirtuaGym"

        api_url = "https://api.virtuagym.com/api/v1/club/{club_id}/membership/instance".format(
            club_id=branch.virtuagym_club_id
        )
        params = {
            "api_key": branch.virtuagym_api_key,
            "club_secret": branch.virtuagym_club_secret,
        }
        body = {
            "membership_id": membership_id,
            "member_id": member_id,
            "start_date": start_date,
            "payment_method": payment_method,
            "salesperson_id": salesperson_id,
        }

        try:
            response = requests.post(api_url, params=params, json=body)
            self._log_virtuagym_action(
                'membership', branch, api_url, {'params': params, 'body': body},
                response=response, sale_order=sale_order,
            )
            data = response.json() if response.content else {}
            if response.status_code == 200 and data.get("result"):
                return True, data["result"].get("id"), "OK"
            return False, None, data.get("status", {}).get("statusmessage")
        except Exception as e:
            self._log_virtuagym_action(
                'membership', branch, api_url, {'params': params, 'body': body},
                error=str(e), sale_order=sale_order,
            )
            return False, None, str(e)

    def update_virtuagym_member(self, vals, branch):

        if branch.virtuagym_api_key:
            api_key = branch.virtuagym_api_key
            api_url = "https://api.virtuagym.com/api/v1/club/{club_id}/member"
            club_secret = branch.virtuagym_club_secret
            club_id = branch.virtuagym_club_id
            api_url = api_url.format(club_id=club_id)
        else:
            return False, None, "La sucursal no tiene configurada la API Key de VirtuaGym"

        headers = {
            "Content-Type": "application/json",
        }
        params = {
            "api_key": api_key,
            "club_secret": club_secret
        }

        body = {
            "firstname": vals.get('firstname'),
            "lastname": vals.get('lastname'),
            "club_member_id": vals.get('vat'),
            "email": vals.get('email'),
            "active": True,
            "is_pro": True,
            "gender": vals.get('gender'),
            "birthday": vals.get('birthday').__str__(),
            "country": "EC",
            "mobile": vals.get('mobile'),
            "lang": "es",
            "street": vals.get('street', ''),
        }
        
        if vals.get('member_id'):
            body['member_id'] = vals.get('member_id')

        api_url2 = f"{api_url}/{vals.get('member_id')}"  # Use the member_id in the URL
        try:
            response = requests.put(api_url2, headers=headers, params=params,json=body)
            self._log_virtuagym_action('update', branch, api_url2, {'params': params, 'body': body}, response=response)

            if response.status_code == 200:
                data = response.json()
                if data.get("result"):
                    return True, data["result"].get('member_id'), "OK"  # Return member data if found
            else:
                return False, None, response.json().get('statusmessage')  # error handling

        except Exception as e:
            self._log_virtuagym_action('update', branch, api_url2, {'params': params, 'body': body}, error=str(e))
            return False, None, str(e)

    def search_virtuagym_member(self, vat):
        """
        Search for a VirtuaGym member by email.
        """
        exists, member_data = self.check_virtuagym_member(vat=vat)
        if exists:
            member_data_new = {
                'firstname': member_data.get('firstname'),
                'lastname': member_data.get('lastname'),
                'email': member_data.get('email'),
                'member_id': member_data.get('member_id'),
                # Virtuagym devuelve 'mobile'; en Odoo 19 se guarda en 'phone'
                'phone': member_data.get('mobile'),
                'vat': member_data.get('club_member_id'),
                'birthday': member_data.get('birthday'),
                'gender': member_data.get('gender'),         
                'street': member_data.get('street', ''),
            }                
            
            new_partner = self.create(member_data_new)  
            return new_partner          
        else:            
            return None
    
    def can_edit_vat(self):
        """ `vat` is a commercial field, synced between the parent (commercial
        entity) and the children. Only the commercial entity should be able to
        edit it (as in backend)."""
        self.ensure_one()
        return True
    
    @api.model
    def _commercial_fields(self):
        """ Returns the list of fields that are managed by the commercial entity
        to which a partner belongs. These fields are meant to be hidden on
        partners that aren't `commercial entities` themselves, and will be
        delegated to the parent `commercial entity`. The list is meant to be
        extended by inheriting classes. """
        return ['company_registry', 'industry_id']
    
    def name_get(self):
        result = []
        for partner in self:
            name = partner.name or ''
            if partner.vat:
                name = f"{name} [{partner.vat}]"
            result.append((partner.id, name))
        return result
