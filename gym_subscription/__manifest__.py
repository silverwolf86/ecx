#Implementacion subscripciones

{
    'name': 'gym subscription',
    'version': '19.0.1.0.0',
    'category': 'Sales/Subscriptions',
    'sequence': 115,
    'summary': 'Generate recurring invoices and manage renewals',
    'description': """
This module allows you to manage subscriptions.

Features:
    - Create & edit subscriptions
    - Modify subscriptions with sales orders
    - Generate invoice automatically at fixed intervals
""",
    'author': 'Franco',
    'depends': [
        'sale_management',
        'portal',
        'rating',
        'sms',
    ],
    'data': [
        'security/sale_subscription_security.xml',
        'security/ir.model.access.csv',
        'wizard/sale_subscription_close_reason_wizard_views.xml',
        'wizard/sale_subscription_change_customer_wizard_views.xml',
        'wizard/res_config_settings_views.xml',
        'wizard/sale_make_invoice_advance_views.xml',

        'views/sale_subscription_plan_views.xml',
        'views/sale_order_views.xml',
        'views/sale_order_template_views.xml',
        'views/product_template_views.xml',
        'views/product_pricelist_views.xml',
        'views/product_pricelist_item_views.xml',
        'views/product_product_views.xml',
        'views/sale_subscription_views.xml',
        'views/sale_order_line_views.xml',
        'views/res_partner_views.xml',
        'views/account_analytic_account_views.xml',
        'views/sale_subscription_portal_templates.xml',
        'views/subscription_templates.xml',
        'views/payment_form_templates.xml',
        'views/mail_activity_plan_views.xml',
        'views/mail_activity_views.xml',

        'views/sale_subscription_menus.xml',

        'data/mail_template_data.xml',
        'data/sale_subscription_data.xml',
        'data/sms_template_data.xml',
        'data/sale_subscription_tour.xml',

        'report/sale_subscription_report_view.xml',
        'report/sale_order_log_report_view.xml',
    ],
    'demo': [
        'data/sale_subscription_demo.xml'
    ],
    'application': True,
    'pre_init_hook': '_pre_init_sale_subscription',
    'assets': {
        'web.assets_backend': [
            'gym_subscription/static/src/js/components/**/*',
            'gym_subscription/static/src/js/product_catalog/**/*',
            'gym_subscription/static/src/js/combo_configurator_dialog/*',
            'gym_subscription/static/src/js/product_configurator_dialog/*',
            'gym_subscription/static/src/js/sale_product_field.js',
            'gym_subscription/static/src/js/tours/sale_subscription.js',
        ],
        'web.assets_frontend': [
            'gym_subscription/static/src/interactions/**/*',
            'gym_subscription/static/src/xml/*.xml',
        ]
    }
}
