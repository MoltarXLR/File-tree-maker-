"""Tests for Folder Template Maker.

A watchdog guards the whole run: if the suite stalls (for example a window waiting for a click that
will never come), every thread's stack is printed and the process exits, instead of hanging for
hours.  Set FTM_TEST_TIMEOUT to change the limit in seconds (0 turns it off).
"""

import faulthandler
import os
import sys

_TIMEOUT = int(os.environ.get("FTM_TEST_TIMEOUT", "300"))
if _TIMEOUT > 0:
    faulthandler.dump_traceback_later(_TIMEOUT, exit=True, file=sys.stderr)
