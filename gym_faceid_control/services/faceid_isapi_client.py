import requests
import logging

_logger = logging.getLogger(__name__)

class FaceIdIsapiClient:
    def __init__(self, base_url, username, password):
        # base_url is the bridge URL (e.g., cloudflare tunnel)
        self.base_url = base_url.rstrip('/') if base_url else ''
        self.credentials = {
            "username": username,
            "password": password
        }
        self.timeout = 30
        self.verify = False

    def _request(self, method, endpoint, payload=None):
        url = f"{self.base_url}/forward"
        bridge_payload = {
            "method": method,
            "endpoint": endpoint,
            "payload": payload,
            "credentials": {
                "username": self.credentials["username"],
                "password": self.credentials["password"]
            }
        }
        try:
            response = requests.post(
                url,
                json=bridge_payload,
                timeout=self.timeout,
                verify=self.verify
            )
            # The bridge returns a JSON with { status_code, text, ok, json }
            if response.ok:
                return {
                    'status_code': response.status_code,
                    'text': response.text,
                    'ok': True,
                    'json': response.json().get('json'),
                    'payload': payload,
                }
            else:
                return {
                    'status_code': response.status_code,
                    'text': f"Bridge Error: {response.text}",
                    'ok': False,
                    'json': None,
                    'payload': payload,
                }
        except Exception as e:
            _logger.error(f"FaceID Bridge request error: {e}")
            return {
                'status_code': 500,
                'text': str(e),
                'ok': False,
                'json': None,
                'payload': payload,
            }

    def search_user(self, employee_no):
        """ Búsqueda de usuario (Caso A) """
        endpoint = "/ISAPI/AccessControl/UserInfo/Search?format=json"
        payload = {
            "UserInfoSearchCond": {
                "searchID": "1",
                "searchResultPosition": 0,
                "maxResults": 10,
                "EmployeeNoList": [
                    {"employeeNo": str(employee_no)}
                ]
            }
        }
        return self._request('POST', endpoint, payload)

    def create_user(self, employee_no, name, enable, begin_time, end_time, branch_id=None):
        """ Creación de usuario (Caso B) """
        endpoint = "/ISAPI/AccessControl/UserInfo/Record?format=json"

        enable_bool = bool(enable)

        name_val = str(name or '')
        user_info = {
            "employeeNo": str(employee_no),
            "name": name_val[:32],
            "userType": "normal",
        }

        if branch_id == 1:
            user_info["RightPlan"] = [
                {
                    "doorNo": 1,
                    "planTemplateNo": "1"
                }
            ]

        user_info["Valid"] = {
            "enable": enable_bool,
            "beginTime": begin_time,
            "endTime": end_time,
            "timeType": "local"
        }

        payload = {
            "UserInfo": user_info
        }

        # Odoo makes the bridge call
        return self._request('POST', endpoint, payload)

    def modify_user(self, employee_no, enable, begin_time=None, end_time=None, branch_id=None):
        """ Modificación de usuario (Caso C) """
        endpoint = "/ISAPI/AccessControl/UserInfo/Modify?format=json"

        enable_bool = bool(enable)

        valid_data = {
        }


        if begin_time:
            valid_data["beginTime"] = begin_time
        if end_time:
            valid_data["endTime"] = end_time

        user_info = {
            "employeeNo": str(employee_no),
            "userType": "normal" if enable_bool else "blackList",
        }
        _logger.info("Modifying user %s from ", branch_id)
        if branch_id == 1:
            user_info["RightPlan"] = [
                {
                    "doorNo": 1,
                    "planTemplateNo": "1"
                }
            ]

        user_info["Valid"] = valid_data

        payload = {
            "UserInfo": user_info
        }

        _logger.info("Modifying user %s from ", payload)

        return self._request('PUT', endpoint, payload)
