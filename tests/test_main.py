"""
Test module for NDN/gRPC conversion functionality.
"""

import pytest
from python_project.utils import setup_logging


class TestUtils:
    """Test cases for utility functions."""
    
    def test_setup_logging(self):
        """Test setup_logging function."""
        # This should not raise an exception
        setup_logging("INFO")
        setup_logging("DEBUG")
        setup_logging("WARNING")
        setup_logging("ERROR")
