"""
Compatibility import for the active discovery implementation.

The project still imports `common.discovery`, but the real implementation now
lives in `common.discovery_v2`.
"""

import sys

from . import discovery_v2 as _discovery_v2


sys.modules[__name__] = _discovery_v2
