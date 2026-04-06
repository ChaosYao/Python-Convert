"""
NDN/gRPC Conversion Project

A project for converting between NDN Interest/Data packets and gRPC messages.
"""

__version__ = "0.1.0"

from .ndn import NDNClient, NDNServer

__all__ = ["NDNClient", "NDNServer", "__version__"]
