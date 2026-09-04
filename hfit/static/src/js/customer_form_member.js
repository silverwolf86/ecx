/** @odoo-module **/ 
import publicWidget from "@web/legacy/js/public/public_widget";
import { loadJS } from "@web/core/assets";

console.log('customer_form_member.js cargado correctamente');

publicWidget.registry.CustomerFormMemberHfit = publicWidget.Widget.extend({
    selector: '#customer_data_form_member', // Tu selector del formulario
    events: {
        'change #is_delivery_same': '_onDeliverySameChange',
    },

    /**
     * @override
     */
    start: function () {
        console.log('CustomerFormMemberWidget (ES6 import) inicializado para el selector:', this.selector);
        this._updateDeliveryFieldsVisibility(); // Llamada inicial para establecer la visibilidad correcta
        return this._super.apply(this, arguments); // No olvides llamar al super
    },

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * Manejador para el cambio en el checkbox.
     * @private
     * @param {Event} ev
     */
    _onDeliverySameChange: function (ev) {
        console.log('Checkbox #is_delivery_same cambió.');
        this._updateDeliveryFieldsVisibility();
    },

    //--------------------------------------------------------------------------
    // Private
    //--------------------------------------------------------------------------

    /**
     * Actualiza la visibilidad de los campos de la dirección de entrega
     * y sus atributos 'required'.
     * @private
     */
    _updateDeliveryFieldsVisibility: function () {
        var $checkbox = this.$('#is_delivery_same');
        // Asumimos que tienes un div que envuelve los campos de dirección de entrega
        // con el ID 'delivery_address_fields' en tu plantilla QWeb.
        var $deliveryFieldsDiv = this.$('#delivery_address_fields'); 

        console.log('Actualizando visibilidad de campos de entrega. Checkbox checked:', $checkbox.is(':checked'));

        if ($checkbox.length === 0) {
            console.warn("El checkbox '#is_delivery_same' no fue encontrado. Verifica tu selector y plantilla.");
            return;
        }
        if ($deliveryFieldsDiv.length === 0) {
            console.warn("El div '#delivery_address_fields' no fue encontrado. Verifica tu selector y plantilla.");
            // Si no existe el div, no podemos hacer nada más aquí.
            // Podrías querer que el checkbox no funcione o se oculte si el div no está.
            return;
        }

        if ($checkbox.is(':checked')) {
            $deliveryFieldsDiv.hide();
            // Haz que los campos dentro de la sección de entrega no sean obligatorios
            // Sé específico con los campos que manipulas para 'required'
            $deliveryFieldsDiv.find('input[name^="delivery_"], select[name^="delivery_"]').removeAttr('required');
        } else {
            $deliveryFieldsDiv.show();
            // Haz que los campos específicos dentro de la sección de entrega SÍ sean obligatorios
            // Ejemplo:
            $deliveryFieldsDiv.find('input[name="delivery_name"]').attr('required', 'required');
            $deliveryFieldsDiv.find('input[name="delivery_street"]').attr('required', 'required');
            $deliveryFieldsDiv.find('input[name="delivery_city"]').attr('required', 'required');
            $deliveryFieldsDiv.find('select[name="delivery_country_id"]').attr('required', 'required');
            // Añade otros campos que necesites que sean obligatorios aquí
        }
    }
});

// Exportar la clase del widget (opcional, pero buena práctica si otros módulos JS pudieran extenderlo)
//export default CustomerFormMemberWidget;