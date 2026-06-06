# Phase 1 test plan:
#
# Functional unit tests:
from . import test_sql_builder_unit          # builder produces correct SQL/params
from . import test_report_execution          # audit model lifecycle and hashing
from . import test_payload_codec             # zlib JSON codec round trip
from . import test_xlsx_writer               # XLSX writer shape and formats
from . import test_privilege_groups          # new privilege groups, implications, ACL pointers
#
# Integration tests (require an installed account module and demo data):
from . import test_cache_invalidation        # account.move state changes bump version
from . import test_sql_builder_integration   # builder executes against real data
from . import test_dynamic_report            # orchestrator render path and cache behaviour
from . import test_report_wizard             # wizard build_options and export action
#
# Performance / pressure scaffolding (post_install tag, gated on perf threshold):
from . import test_perf_sql_builder
from . import test_report_fold_state
