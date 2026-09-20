{
    'name': 'Inbox Document',
    'version': '19.0.1.0.0',
    'summary': 'Carga de claves de acceso del SRI y generación de documentos de compra',
    'category': 'Accounting/Localizations',
    'license': 'LGPL-3',
    'author': 'franco',
    'depends': [
        'account',
        'mail',
        'l10n_ec',
        'ecx_edi',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/inbox_document_import_view.xml',
        'views/inbox_document_view.xml',
        'views/account_move_view.xml',
        'views/menuitem.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'inbox_document/static/src/js/inbox_document_btn.js',
            'inbox_document/static/src/xml/inbox_document_template.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
