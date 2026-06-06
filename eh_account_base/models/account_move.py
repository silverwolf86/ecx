# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""
account.move extension: bump the per company move version counter on state
changes. Drives reporting cache invalidation.

Hooks the write() method rather than _post() so every state transition
(post, draft, cancel) participates uniformly. Posting is implemented via
write({'state': 'posted'}) under the hood, so this single hook covers all
transitions without missing edge cases.
"""

from odoo import api, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model_create_multi
    def create(self, vals_list):
        """Bump version when a move is created already in posted state.

        Common case is unaffected (moves are created in draft and posted via
        action_post, which goes through write()). This override exists for the
        rare paths that create directly with state='posted', so the cache stays
        consistent.
        """
        moves = super().create(vals_list)
        posted = moves.filtered(lambda m: m.state == 'posted')
        if posted:
            company_ids = set(posted.mapped('company_id.id'))
            if company_ids:
                self.env['res.company'].sudo()._eh_bump_move_version(company_ids)
        return moves

    def write(self, vals):
        # Snapshot the prior state per id so we only bump the move
        # version counter when state actually changes. The previous
        # implementation bumped on every write that *included* state in
        # vals, even when the new value matched the old, which produced
        # spurious cache invalidation during routine recomputes.
        if 'state' in vals and self:
            new_state = vals['state']
            changed_ids = [m.id for m in self if m.state != new_state]
        else:
            changed_ids = []
        result = super().write(vals)
        if changed_ids:
            changed = self.browse(changed_ids)
            company_ids = set(changed.mapped('company_id.id'))
            if company_ids:
                self.env['res.company'].sudo()._eh_bump_move_version(company_ids)
        return result
