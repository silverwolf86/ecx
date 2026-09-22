import json

from odoo import Command, api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    inbox_invoice_id = fields.Many2one(
        comodel_name='inbox.document',
        string='Documento Entrada',
        copy=False,
    )
    inbox_invoice_id_domain = fields.Char(
        compute='_compute_inbox_invoice_id_domain',
        readonly=True,
        store=False,
    )
    autorizacion = fields.Char(string='Número de Autorización', copy=False)
    inbox_requiere_revision = fields.Boolean(related='inbox_invoice_id.requiere_revision')

    @api.depends('partner_id', 'move_type')
    def _compute_inbox_invoice_id_domain(self):
        doc_types = {
            'in_invoice': self.env.ref('l10n_ec.ec_dt_01'),
            'in_refund': self.env.ref('l10n_ec.ec_dt_04'),
        }
        for rec in self:
            domain = [('estado', '=', 'consultado')]
            doc_type = doc_types.get(rec.move_type)
            if doc_type:
                domain.append(('tipo_documento', '=', doc_type.id))
            if rec.partner_id:
                domain.append(('partner_id', '=', rec.partner_id.id))
            rec.inbox_invoice_id_domain = json.dumps(domain)

    @api.onchange('inbox_invoice_id')
    def _onchange_inbox_invoice_id(self):
        document = self.inbox_invoice_id
        if not document:
            return
        if not self.partner_id:
            self.partner_id = document.partner_id
        self.autorizacion = document.numero_autorizacion or document.clave_acceso
        self.invoice_date = document.fecha_emision
        self.narration = document.info_adicional
        if not self.l10n_latam_document_number:
            self.l10n_latam_document_number = document.numero_comprobante

        fiscal_position = self.fiscal_position_id or self.partner_id.with_company(
            self.company_id
        ).property_account_position_id
        self.invoice_line_ids = [Command.clear()] + document._prepare_invoice_line_vals(
            fiscal_position
        )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        # Si el partner cambia manualmente, el documento vinculado deja de ser válido.
        self.inbox_invoice_id = False
        return super()._onchange_partner_id()

    def action_post(self):
        res = super().action_post()
        self.inbox_invoice_id.filtered(lambda doc: doc.estado != 'procesado').estado = 'procesado'
        return res
