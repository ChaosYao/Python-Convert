"""
Test configuration and fixtures for NDN/gRPC conversion project.
"""

import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent
