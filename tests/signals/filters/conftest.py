"""Pytest configuration for tests/signals/filters.

Suppresses known third-party library warnings that are unrelated to the
code under test and would otherwise cause spurious failures under -W error.

filterpy 1.4.5 contains an invalid escape sequence (backslash-S) in a
docstring inside filterpy/common/helpers.py.  In Python 3.12 this triggers
a SyntaxWarning at module compilation time; in Python 3.13 it will become a
hard SyntaxError.  The warning is irrelevant to our numeric results.
"""
from __future__ import annotations

import contextlib
import warnings

# Pre-import filterpy with SyntaxWarning suppressed so that the compiled
# bytecode is cached before pytest activates -W error.  Once cached,
# subsequent imports in test functions will not re-trigger the warning.
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=SyntaxWarning)
    with contextlib.suppress(Exception):
        import filterpy.kalman  # noqa: F401
