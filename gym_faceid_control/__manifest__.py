{
    'name': 'Gym FaceID Control',
    'version': '1.0',
    'summary': 'Módulo para integración ISAPI (JSON) FaceID Hikvision',
    'description': 'Módulo para control de acceso, suscripciones y logs de FaceID usando ISAPI.',
    'author': 'Franco',
    'category': 'Sales/Sales',
    'depends': ['base', 'sale', 'gym_subscription', 'hfit', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'views/faceid_log_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
