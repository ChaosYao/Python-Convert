"""
Entry point for running python_project as a module.

This allows the package to be executed with:
    python -m python_project [server|client]
"""

from .main import main

if __name__ == '__main__':
    main()

