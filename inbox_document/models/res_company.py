from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    inbox_retencion_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Diario de retenciones recibidas',
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
    )
    inbox_retencion_iva_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta retención IVA',
    )
    inbox_retencion_renta_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta retención en la fuente',
    )
    inbox_retencion_credit_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta contrapartida de retenciones',
    )
