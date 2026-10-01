def migrate(cr, version):
    # La versión 19.0.1.0.0 creaba los inputs BONO/DESC sin xml_id dentro de
    # input_ids; ahora son registros con xml_id. Se borran los anteriores para
    # no duplicarlos en "Other Inputs".
    cr.execute("""
        DELETE FROM hr_rule_input
         WHERE input_id IN (
                SELECT res_id
                  FROM ir_model_data
                 WHERE module = 'hfit_payroll_ecuador'
                   AND model = 'hr.salary.rule'
                   AND name IN ('hr_salary_rule_bono_puntual_ec',
                                'hr_salary_rule_desc_puntual_ec'))
           AND id NOT IN (
                SELECT res_id
                  FROM ir_model_data
                 WHERE model = 'hr.rule.input')
    """)
