# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
{
 'name': "Accounting Suite Base",
 'summary': "Shared engine for the ERP Heritage accounting suite. Reproducible report audit log, result cache, parameterised SQL builder. Auto-installs with any ERP Heritage accounting module.",
 'description': """
ERP Heritage Accounting Suite Base
====================================

The shared engine that powers the ERP Heritage accounting modules for
Odoo 19 Community. Auto-installs as a dependency of any ERP Heritage
accounting module so you do not need to install it manually.

What this module gives you directly
-----------------------------------

* **Reproducible report audit log.** Every report render is recorded as
  an eh.account.report.execution row: who ran it, when, with which
  parameters, how long it took, and a SHA-256 hash of the result. An
  auditor can re-render the exact report from a stored options snapshot.

* **Precise cache invalidation.** A per company move version counter
  bumps on every account.move state change, so cached report results
  are served on cache hit and recomputed the moment the underlying
  ledger changes.

* **Parameterised SQL builder.** A multi-company, currency-table aware
  query composer that the report handlers use on the hot path. No raw
  user input ever interpolates into SQL, no cross-company leakage.

What other ERP Heritage modules build on top
---------------------------------------------

* Dynamic Account Reports (free): P&L, Balance Sheet, Trial Balance,
  General Ledger, Aged Receivable / Payable, Cash Flow, Partner Ledger.
* Dynamic Reports Pro: drag-and-drop custom report builder, scheduled
  email delivery, multi-period forecasting, budget variance.
* Bank Reconciliation Pro, Collections Workbench, Period Close Workflow,
  Multi-Version Budget Pro, Recurring Invoices Pro, Post-Dated Cheques,
  FX Period-End Revaluation, IFRS 16 Lease and Fixed Assets,
  Vendor Bill Automation.

Engineering principles
----------------------

* No silent fallbacks. Missing rates, missing accounts, missing
  configuration each surface explicit messages.
* Multi-company aware throughout. Every report query enforces the
  current company scope.
* Plain Python tools (SQL builder, cache, codec) are unit-tested
  without the ORM, which keeps the hot path predictable.

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
 'version': '19.0.1.5.0',
 'depends': [
 'account',
 ],
 'data': [
 'security/eh_security.xml',
 'security/eh_isolation_rules.xml',
 'security/ir.model.access.csv',
 'data/paperformat.xml',
 'report/eh_report_base.xml',
 'report/account_move_report.xml',
 'views/report_execution_views.xml',
 'views/dynamic_report_views.xml',
 'views/report_wizard_views.xml',
 'views/res_config_settings_views.xml',
 'data/menus.xml',
 ],
 'demo': [
 'demo/base_demo.xml',
 ],
 'images': ['static/description/banner.png'],
 'installable': True,
 'application': False,
 'auto_install': False,
 'post_init_hook': 'post_init_hook',
}
