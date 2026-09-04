/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { patch } from "@web/core/utils/patch";

const FINAL_CONSUMER_VAT = "9999999999999";

patch(OrderPaymentValidation.prototype, {
    async isOrderValid(isForceValidate) {
        const res = await super.isOrderValid(...arguments);
        if (!res) {
            return false;
        }

        const hasPayrollDiscount = this.paymentLines.some(
            (line) => line.payment_method_id.is_payroll_discount
        );

        if (!hasPayrollDiscount) {
            return true;
        }

        const partner = this.order.getPartner();

        if (!partner) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Cliente requerido"),
                body: _t("Los pagos por descuento a rol requieren seleccionar un cliente."),
            });
            return false;
        }

        if (partner.vat === FINAL_CONSUMER_VAT) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Cliente no permitido"),
                body: _t(
                    "No se permite utilizar el cliente Consumidor Final para pagos por descuento a rol."
                ),
            });
            return false;
        }

        if (!partner.pos_employee_id) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Empleado no encontrado"),
                body: _t(
                    "El cliente seleccionado no tiene un empleado asociado, por lo que no puede utilizar pagos por descuento a rol."
                ),
            });
            return false;
        }

        return true;
    },
});
