# -*- coding: utf-8 -*-
{
    'name': "Hr Face Attendance",

    'summary': "Check In and Check Out using Face Recognition",

    'description': """
Check In and Check Out using Face Recognition for Any Devices.
    """,
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'author': "Ye Htut Swe",
    'website': "yehtutswe59@gmail.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'HR',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base','hr','hr_attendance','web'],
    'images' : ['static/description/icon.png'],
    # always loaded
    'data': [
        # 'security/ir.model.access.csv',
        # 'views/hr_attendance.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}

