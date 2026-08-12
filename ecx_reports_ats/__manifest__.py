# -*- coding: utf-8 -*-

{
    'name': 'Ecuador - ATS Report',
    'version': '1.0',
    'category': 'Accounting/Localizations/Reporting',
    'author': 'odoo',
    'description': """
        ATS Report for Ecuador
    """,
    'depends': [
        'ecx_edi',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ats_report.xml',
        'views/ecx_ats_report_views.xml',
    ],
    'installable': True,
    'auto_install': True,
}
