"""
gRPC bidirectional streaming demo program.

Usage:
1. Run server in one terminal:
   python examples/grpc_bidirectional_demo.py server

2. Run client in another terminal:
   python examples/grpc_bidirectional_demo.py client
"""
import sys
import logging
from pathlib import Path

# Add project root directory to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from python_project.grpc.server import run_server
from python_project.grpc.client import run_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Main function."""
    if len(sys.argv) < 2:
        logger.error("Usage:")
        logger.error("  Server: python grpc_bidirectional_demo.py server [port]")
        logger.error("  Client: python grpc_bidirectional_demo.py client [host:port]")
        sys.exit(1)
    
    mode = sys.argv[1].lower()
    
    if mode == "server":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 50051
        logger.info(f"Starting gRPC server on port {port}...")
        run_server(port)
    elif mode == "client":
        server_address = sys.argv[2] if len(sys.argv) > 2 else "localhost:50051"
        logger.info(f"Connecting to server {server_address}...")
        # Simple demo data: (value, payload) tuples
        data_list = [
            (1, "data1"),
            (2, "data2"),
            (3, "data3"),
            (4, "data4"),
        ]
        run_client(server_address, data_list)
    else:
        logger.error(f"Unknown mode: {mode}")
        logger.error("Supported modes: server, client")
        sys.exit(1)


if __name__ == "__main__":
    main()

