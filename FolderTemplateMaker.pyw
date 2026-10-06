"""Double-click this file (needs Python 3.9 or newer, installed from python.org) to start
Folder Template Maker.  The .pyw ending means no black console window appears."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from foldertemplatemaker.app import main  # noqa: E402

sys.exit(main())
