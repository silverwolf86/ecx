{
    'name': 'HFIT Payroll Ecuador',
    'version': '19.0.1.6.0',
    'category': 'Human Resources',
    'summary': 'Reglas salariales y campos de contrato para nómina de Ecuador '
               '(décimos, fondos de reserva, IESS, provisiones) y pago de '
               'nóminas',
    'author': 'HFIT',
    'depends': ['hr_payroll_account_community', 'l10n_latam_base'],
    'data': [
        'data/hr_salary_rule_data.xml',
        'data/hr_payslip_actions.xml',
        'data/ir_sequence_data.xml',
        'views/hr_version_views.xml',
        'views/hr_payslip_views.xml',
        'views/account_payment_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
