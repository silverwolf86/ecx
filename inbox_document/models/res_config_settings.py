from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    inbox_retencion_journal_id = fields.Many2one(
        related='company_id.inbox_retencion_journal_id',
        readonly=False,
    )
    inbox_retencion_iva_account_id = fields.Many2one(
        related='company_id.inbox_retencion_iva_account_id',
        readonly=False,
    )
    inbox_retencion_renta_account_id = fields.Many2one(
        related='company_id.inbox_retencion_renta_account_id',
        readonly=False,
    )
    inbox_retencion_credit_account_id = fields.Many2one(
        related='company_id.inbox_retencion_credit_account_id',
        readonly=False,
    )
