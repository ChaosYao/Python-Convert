"""
Entry point for running python_project as a module (Sidecar mode).

This allows the package to be executed with:
    python -m python_project [server|sidecar]
    
Default mode is 'sidecar' (both gRPC Server and NDN Server).
"""

from .main import main

if __name__ == '__main__':
    main()

