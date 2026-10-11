"""Write the generated EURUSD test candles into a directory laid out like the Dukascopy datafeed.

    python -m tests.make_mirror /tmp/el-mirror
    EL_DUKASCOPY_BASE_URL=file:///tmp/el-mirror uvicorn app.main:app      # used by the Playwright journey

The candles are synthetic test fixtures, not market history.
"""

import sys
from pathlib import Path

from tests.md_helpers import write_eurusd_fixture

if __name__ == "__main__":
    root = Path(sys.argv[1])
    write_eurusd_fixture(root)
    print(f"wrote test candles under {root}")
