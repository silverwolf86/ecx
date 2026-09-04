from odoo import http
from odoo.http import request
import base64

class WebsiteCustomer(http.Controller):

    @http.route(['/shop/checkout'], type='http', auth="public", website=True)
    def custom_checkout_redirect(self, **kw):
        return request.redirect('/customer_lookup')

    @http.route('/customer_lookup', type='http', auth='public', website=True)
    def customer_lookup_form(self, **kw):
        """Muestra la página inicial para buscar cliente por cédula."""
        return request.render('hfit.customer_lookup_page')

    @http.route('/customer_details', type='http', auth='public', website=True, methods=['POST', 'GET'])
    def customer_details_form(self, vat_number=None, **post):
        """
        Maneja la búsqueda por cédula (POST desde /customer_lookup) o muestra el formulario.
        Si se accede por GET con un partner_id, muestra los datos para editar.
        """
        partner = None
        delivery_address = None
        message = None
        
        branches = request.env['res.branch'].sudo().search([])

        if request.httprequest.method == 'POST' and vat_number: # Búsqueda desde /customer_lookup           
            if vat_number:
                partner = request.env['res.partner'].sudo().search([('vat', '=', vat_number)], limit=1)                            
                if not partner:
                    # Cliente no existe, preparamos para crear uno nuevo con esta cédula
                    message = "Cliente no encontrado. Puede crear uno nuevo."
                    # Pasamos el VAT para pre-rellenar el campo en el formulario de creación
                    return request.render('hfit.customer_form_page', 
                                          {'vat_new': vat_number, 
                                           'message': message, 
                                           'branches':branches })
        
        elif 'partner_id' in post: # Viniendo de guardar o para editar directamente (si tuvieras un listado)
             partner = request.env['res.partner'].sudo().browse(int(post.get('partner_id')))
       

        # Si partner existe, se pasa al template para edición.
        # Si partner no existe y no se buscó VAT, se muestra el formulario vacío para crear.
        # Si se buscó VAT y no se encontró, el mensaje ya está puesto.
        
        return request.render('hfit.customer_form_page', {
            'partner': partner,
            'delivery_address': delivery_address,
            'is_same_invoice' : False,
            'message': message,
            'vat_new': vat_number if not partner and vat_number else None, 
            'branches': branches,
        })

    @http.route('/customer_save', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def customer_save(self, **post):
        """Guarda los datos del cliente (crea o actualiza)."""

        branches = request.env['res.branch'].sudo().search([])

        required_fields_contact = ['lastname', 'email', 'vat', 'mobile', 'contact_street','company_id']
        errors = {}
        for field in required_fields_contact:
            if not post.get(field):
                errors[field] = 'Este campo es obligatorio.'
        
        is_delivery_same = post.get('is_delivery_same') == 'on'
        if not is_delivery_same:
            required_fields_delivery = [] # ['invoice_name', 'invoice_vat', 'invoice_street','invoice_email','invoice_mobile']
            for field in required_fields_delivery:
                if not post.get(field):
                    errors[field] = 'Este campo de factura es obligatorio.'
        
        if errors:
            # Recargar el formulario con errores y datos ingresados
            # Necesitas recuperar 'partner' y 'invoice' si estaban en edición
            partner_id = post.get('partner_id')
            partner = request.env['res.partner'].sudo().browse(int(partner_id)) if partner_id else None
            delivery_address = None
            
            return request.render('hfit.customer_form_page', {
                'partner': partner,
                'delivery_address': delivery_address,
                'submitted_values': post,
                'errors': errors,
                'vat_new': post.get('vat') if not partner_id else None,
                'branches': branches,
            })

        file = request.httprequest.files.get('profile_photo')
        image_base64 = base64.b64encode(file.read()) if file and file.filename else False

        partner_id = post.get('partner_id')
        partner_vals = {
            'firstname': post.get('firstname'),
            'lastname': post.get('lastname'),
            'vat': post.get('vat'),
            'email': post.get('email'),
            'mobile': post.get('mobile'),
            'street': post.get('contact_street'),
            'city': 'Quito',
            'country_id': 63,
            'gender': post.get('gender'),
            'birthday': post.get('birthday'),
            'member_branch_id': int(post.get('company_id')),
            'image_1920': image_base64
        }

        partner = None
        if partner_id: # Actualizar cliente existente
            partner = request.env['res.partner'].sudo().browse(int(partner_id))
            partner.write(partner_vals)
        else: # Crear nuevo cliente
            # Validar si la cédula (VAT) ya existe antes de crear
         
            
            existing_partner = request.env['res.partner'].sudo().search([('vat', '=', partner_vals['vat'])], limit=1)
            if existing_partner:
                return request.render('hfit.customer_form_page', {
                    'error_vat': 'Un cliente con esta cédula ya existe.',
                    'submitted_values': post,
                    'vat_new': partner_vals['vat']
                })
            partner = request.env['res.partner'].sudo().create(partner_vals)

        # Gestionar dirección de entrega
        is_delivery_same = False

        if is_delivery_same:
            if invoice_partner: # Si existe una dirección de entrega diferente, la actualizamos para que sea igual o la podríamos archivar/eliminar
                print(" escribir el partner")
                # invoice_partner.write({
                #     'name': partner.name, # O un nombre específico como "Entrega: " + partner.name
                #     'street': partner.street,
                #     'city': partner.city,
                #     'zip': partner.zip,
                #     'country_id': partner.country_id.id if partner.country_id else None,
                #     'state_id': partner.state_id.id if partner.state_id else None,
                #     'email': partner.email,
                #     'mobile': partner.mobile,
                #     'member_branch_id' : partner.member_branch_id.id if partner.member_branch_id else False,
                #     'city': 'Quito',
                #     'country_id': 63
                # })
            # Si no hay dirección de entrega y es la misma, no se crea una nueva, se asume la del contacto.
        else: # Dirección de entrega es diferente
            delivery_vals = {
                'name': post.get('invoice_name'),
                'vat': post.get('invoice_vat'),
                'street': post.get('invoice_street'),                
                'type': 'invoice',
                'email': post.get('invoice_email', partner.email),
                'mobile': post.get('invoice_mobile', partner.mobile), 
                'member_branch_id' : post.get('company_id'),
                'city': 'Quito',
                'country_id': 63}
            
            if False:
                invoice_partner.write(delivery_vals)
                invoice_partner.write({
                    'parent_id': partner.id
                    })
            else:
                print("crear partner de factura")
                #invoice_partner = request.env['res.partner'].sudo().create(delivery_vals)

        
        # Guardar partner en la sesión
        company_id = int(post.get('company_id'))
               
        return request.render('hfit.customer_form_success_page', {'partner': partner})