from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_payroll_discount = fields.Boolean(
        string='Descuento por Rol',
        default=False,
        help='Indica que este método de pago corresponde a un descuento por rol de pagos. '
             'Requiere que el cliente tenga un empleado asociado.',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        return fields_list + ['is_payroll_discount']


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # Lo cobrado con descuento a rol es consumo del personal: se descuenta en
    # el rol y no se factura (decisión del 4-nov-2026). ecx_edi_pos abre cada
    # venta del POS con «Factura» marcada; la pantalla de cobro la desmarca
    # (payment_screen_payroll.js) y esto lo asegura en el servidor, también
    # para una caja que siga con la pantalla vieja abierta.

    def _hfit_con_descuento_rol(self):
        self.ensure_one()
        return bool(self.payment_ids.payment_method_id.filtered('is_payroll_discount'))

    def _process_saved_order(self, draft):
        self.ensure_one()
        if self.to_invoice and self._hfit_con_descuento_rol():
            self.to_invoice = False
        return super()._process_saved_order(draft)

    def action_pos_order_invoice(self):
        for order in self:
            if not order.account_move and order._hfit_con_descuento_rol():
                raise UserError(_(
                    'La venta %s se cobró con descuento a rol: es consumo del '
                    'personal y no se factura.', order.name))
        return super().action_pos_order_invoice()
