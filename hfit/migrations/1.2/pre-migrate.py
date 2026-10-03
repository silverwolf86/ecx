def migrate(cr, version):
    # El archivo TXT de pagos al banco se movió de hfit_payroll_ecuador a
    # hfit. Se reasignan los xml_id para que la actualización no borre la
    # columna res_partner_bank.account_type ni duplique la vista y el reporte.
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
           AND NOT EXISTS (
                SELECT 1
                  FROM ir_model_data other
                 WHERE other.module = 'hfit'
                   AND other.name = imd.name)
    """)
