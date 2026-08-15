"""
Shared pytest fixtures for CrowdShield backend tests.

Since tests in this suite do not require a database connection, there is
no DB fixture here. All tested modules are pure Python (no async, no ORM).

If DB integration tests are added later, an async session fixture should
be added here using pytest-asyncio and a test database URL.
"""

import sys
import os

# Ensure the backend/ root is on sys.path so that `from app.xxx import yyy` works
# when pytest is invoked from the backend/ directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
