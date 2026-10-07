"""PyInstaller entry point. hospital_agent/__main__.py uses package-relative imports,
so the frozen executable starts here and calls into the installed package."""

import sys

from hospital_agent.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
