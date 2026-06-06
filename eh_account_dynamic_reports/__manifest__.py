# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
{
 'name': "Dynamic Account Reports",
 'summary': "Next generation dynamic financial reports for Odoo 19 Community: P&L, Balance Sheet, Trial Balance, General Ledger, Aged Partner Balance, Cash Flow, Partner Ledger. Drill down to journal entries, comparatives, XLSX and PDF export. Built to stay fast at 100k plus entries.",
 'description': """
Dynamic Accounting Reports for Odoo 19 Community
=================================================

A faster, better architected alternative to the existing Community reporting modules.
Built natively for Odoo 19 with a tested SQL direct engine that stays responsive
on large databases.

Reports included:

* Profit and Loss
* Balance Sheet
* Trial Balance
* General Ledger
* Partner Ledger
* Aged Receivable
* Aged Payable
* Cash Flow Statement
* Tax Report

Engineering wedges:

* SQL direct query path. No ORM overhead on the hot path.
* Per execution result cache with precise invalidation on entry post.
* Optional periodic snapshot tables for sub second loads on closed periods.
* Drill down: every line clicks through to the underlying journal entries.
* Comparatives: prior period, prior year, custom range, vs budget.
* XLSX and PDF export, both with embedded execution ID for reproducibility.
* Coexists cleanly with other Community accounting modules.

Free anchor for the ERP Heritage accounting suite.
For custom report builder and scheduled email delivery, see eh_account_dynamic_reports_pro.

Search keywords
---------------

Accounting, Full Accounting, Full Accounting for Community, Odoo 19
Community accounting, accounting suite, accounting modules, financial
reporting, period close, accounts receivable, accounts payable, journal
entries, double entry bookkeeping.


    """,
 'author': "ERP Heritage",
 'website': "https://www.erpheritage.com.au/",
 'license': 'LGPL-3',
 'category': 'Accounting/Accounting',
 'version': '19.0.1.3.8',
 'depends': [
 'eh_account_base',
 ],
 'data': [
 # No ACL CSV: every model in this module is an AbstractModel handler
 # or a report renderer. ACLs for the orchestrator (eh.account.dynamic.
 # report) and the audit log (eh.account.report.execution) live in the
 # eh_account_base module which this module depends on. If a concrete
 # (non-abstract, non-transient) model is ever added here, add an
 # ir.model.access.csv at the same time.
 'data/reports.xml',
 'data/paperformat.xml',
 'data/report_pdf.xml',
 'report/report_dynamic_pdf_template.xml',
 'views/res_partner_views.xml',
 'data/menus.xml',
 ],
 'assets': {
 'web.assets_backend': [
 'eh_account_dynamic_reports/static/src/components/**/*',
 ],
 },
 'images': ['static/description/banner.png'],
 'installable': True,
 'application': True,
 'auto_install': False,
}
