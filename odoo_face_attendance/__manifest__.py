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

    'category': 'Human Resources/Attendances',
    'version': '19.0.1.0.0',

    # any module necessary for this one to work correctly
    'depends': ['hr', 'hr_attendance'],
    'external_dependencies': {
        'python': ['face_recognition', 'numpy'],
    },
    'images': ['static/description/icon.png'],
    'data': [],
}
