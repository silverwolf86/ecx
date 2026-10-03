def migrate(cr, version):
    # El archivo TXT de pagos al banco se movió a hfit. Si este módulo se
    # actualiza antes que hfit, se reasignan aquí los xml_id para que no se
    # borre la columna res_partner_bank.account_type.
    cr.execute("""
        UPDATE ir_model_data imd
           SET module = 'hfit'
         WHERE imd.module = 'hfit_payroll_ecuador'
           AND imd.name IN ('view_partner_bank_form_ecuador',
                            'action_report_account_payment_bank_txt',
                            'report_account_payment_bank_txt',
                            'field_res_partner_bank__account_type',
                            'selection__res_partner_bank__account_type__aho',
                            'selection__res_partner_bank__account_type__cte')
           AND EXISTS (
                SELECT 1
                  FROM ir_module_module
                 WHERE name = 'hfit'
                   AND state IN ('installed', 'to upgrade'))
           AND NOT EXISTS (
                SELECT 1
                  FROM ir_model_data other
                 WHERE other.module = 'hfit'
                   AND other.name = imd.name)
    """)
