{
    'name': 'HFIT Payroll Ecuador',
    'version': '19.0.1.1.0',
    'category': 'Human Resources',
    'summary': 'Reglas salariales y campos de contrato para nómina de Ecuador '
               '(décimos, fondos de reserva, IESS, provisiones), pago de '
               'nóminas y archivo TXT para el banco',
    'author': 'HFIT',
    'depends': ['hr_payroll_account_community', 'l10n_latam_base'],
    'data': [
        'data/hr_salary_rule_data.xml',
        'data/hr_payslip_actions.xml',
        'report/account_payment_bank_txt.xml',
        'views/hr_version_views.xml',
        'views/res_partner_bank_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
