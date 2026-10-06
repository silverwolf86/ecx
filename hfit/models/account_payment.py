from markupsafe import Markup

from odoo import models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def _get_bank_txt_values(self):
        """Columnas del archivo de pagos al banco, en orden."""
        self.ensure_one()
        partner = self.partner_id
        # Si el pago se creó sin cuenta del beneficiario, se usa la primera
        # cuenta bancaria del contacto.
        bank = self.partner_bank_id or partner.bank_ids[:1]
        # Hay proveedores con RUC cuya cuenta está a nombre de una persona con
        # cédula: en ese caso la cédula se guarda en el clearing_number de la
        # cuenta y tiene prioridad sobre el vat del contacto.
        if bank.clearing_number:
            vat = bank.clearing_number
            tipo_doc = 'C'
        else:
            vat = partner.vat
            tipo_doc = (partner.l10n_latam_identification_type_id.name or '')[0:1]
        return [
            'PA',                                                       # codigo
            vat,                                                        # contrapartida
            'USD',                                                      # moneda
            str(round(self.amount * 100)),                              # valor (centavos, sin punto)
            'CTA',                                                      # cta
            bank.account_type,                                          # tipo_cuenta
            bank.acc_number,                                            # numero_cuenta
            self.memo,                                                  # referencia
            tipo_doc,                                                   # tipo_doc
            vat,                                                        # cedula
            partner.name,                                               # beneficiario
            bank.bank_id.bic,                                           # banco
        ]

    def _get_bank_txt(self):
        # Markup: es un archivo de texto plano, no se debe escapar como HTML.
        return Markup('\r\n'.join(
            '\t'.join(str(value or '').replace('\t', ' ') for value in pay._get_bank_txt_values())
            for pay in self
        ))
