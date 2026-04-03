"""
Main entry point for NDN/gRPC conversion project (Sidecar mode).

Runs in sidecar mode: both gRPC Server and NDN Server running concurrently.

Configuration via:
1. Configuration file: config.yaml
2. Environment variables
"""
import asyncio
import os
import sys
import logging
import threading
import time
from typing import Optional

from .ndn.server import NDNServer
from .utils import setup_logging, get_hostname, extract_host_from_server_id
from .config import get_config

logger = logging.getLogger(__name__)


def run_sidecar(config_path: Optional[str] = None):
    """
    Run sidecar mode: both gRPC Server and NDN Server running concurrently.
    
    Thread safety:
    - NDN Server runs in its own thread with its own NDNApp instance
    - NDN Client (for gRPC Server) runs in its own thread with its own NDNApp instance
    - gRPC Server runs in async event loop
    """
    config = get_config(config_path)
    
    from .grpc.server import run_server_async
    
    pib_path = config.get_ndn_pib_path()
    tpm_path = config.get_ndn_tpm_path()
    
    # Build route prefix based on hostname: /raft/{host}/
    hostname = get_hostname()
    host = extract_host_from_server_id(hostname)
    logger.info(f"Current hostname: {hostname}, extracted host: {host}")
    route_prefix = f"/raft/{host}"
    logger.info(f"Registering route prefix: {route_prefix}")

    # IMPORTANT: create NDNServer in the SAME thread where app.run_forever() executes.
    # KeychainSqlite3 uses sqlite objects that are thread-affine.
    ndn_server_holder: dict[str, Optional[NDNServer]] = {"server": None}
    ndn_init_done = threading.Event()

    def run_ndn_server_thread():
        """Run NDN Server in a dedicated thread. No restart — the root cause
        (oversized NDN packets / event-loop starvation) must be fixed instead."""
        logger.info("NDN Server thread started")
        ndn_server: Optional[NDNServer] = None
        try:
            ndn_server = NDNServer(pib_path=pib_path, tpm_path=tpm_path, config_path=config_path)
            ndn_server_holder["server"] = ndn_server
            ndn_init_done.set()
            logger.info("NDN Server initialized successfully")

            async def after_nfd_connected():
                loop = asyncio.get_running_loop()
                def _loop_exception_handler(loop, context):
                    exc = context.get('exception')
                    msg = context.get('message', '')
                    logger.error(
                        "NDN event-loop unhandled exception: %s%s",
                        msg,
                        f" — {exc}" if exc else "",
                        exc_info=exc,
                    )
                loop.set_exception_handler(_loop_exception_handler)

                ok = await ndn_server.register_route(route_prefix)
                if ok:
                    logger.info("NDN route registered: %s", route_prefix)
                else:
                    logger.error(
                        "NDN prefix registration failed for %s. "
                        "Check NFD authorization/trust schema and `nfdc route list`.",
                        route_prefix,
                    )

            ndn_server.app.run_forever(after_start=after_nfd_connected())

            # If we reach here, run_forever() exited without exception.
            # This means NFD closed the connection — something sent an invalid
            # packet (check for oversized_ndn_data warnings above this line).
            logger.error(
                "NDN run_forever() EXITED — NFD closed the connection. "
                "prefix=%s is now unreachable. Check logs for oversized_ndn_data "
                "warnings or slow_grpc_call warnings above this line.",
                route_prefix,
            )

        except Exception as e:
            ndn_init_done.set()  # unblock main thread even on failure
            logger.error("NDN Server fatal error: %s", e, exc_info=True)
        finally:
            if ndn_server:
                try:
                    ndn_server.shutdown()
                except Exception:
                    pass

    ndn_server_thread = threading.Thread(target=run_ndn_server_thread, daemon=True)
    ndn_server_thread.start()
    ndn_init_done.wait(timeout=5.0)
    ndn_enabled = ndn_server_holder["server"] is not None
    
    logger.info("=" * 50)
    logger.info("Sidecar mode started")
    logger.info(f"gRPC Server: port {config.get_grpc_server_port()}")
    if ndn_enabled:
        logger.info(f"NDN Server: listening on prefix {route_prefix}")
    else:
        logger.warning("NDN Server: NOT running (initialization failed)")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 50)
    
    # Run gRPC Server in async event loop (main thread)
    try:
        asyncio.run(run_server_async(port=None, config_path=config_path))
    except KeyboardInterrupt:
        logger.info("Shutting down sidecar...")
        if ndn_server_holder["server"] is not None:
            ndn_server_holder["server"].shutdown()
        logger.info("Sidecar stopped")
    except Exception as e:
        logger.error(f"gRPC Server error: {e}", exc_info=True)
        logger.error("Container will keep running for debugging...")
        # Keep container alive for debugging
        # NOTE: do NOT write "import time" here — it would shadow the module-level
        # import and create a closure cell variable that breaks time.sleep() inside
        # the nested run_ndn_server_thread() function with NameError.
        while True:
            time.sleep(60)
            logger.info("Container still running... (Ctrl+C to exit)")






def main():
    """Main entry point."""
    # Check for config file path in command line
    config_path = None
    if len(sys.argv) > 1 and sys.argv[1].startswith('--config='):
        config_path = sys.argv[1].split('=', 1)[1]
        sys.argv = [sys.argv[0]] + sys.argv[2:]
    elif '--config' in sys.argv:
        idx = sys.argv.index('--config')
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]
            sys.argv = sys.argv[:idx] + sys.argv[idx + 2:]
    
    # Get config and setup logging
    config = get_config(config_path)
    log_level = config.get_log_level()
    setup_logging(log_level)
    
    logger.info("NDN Interest/Data Demo")
    logger.info("Note: This demo requires NDN network to be running.")
    logger.info("For local testing, you may need to set up NFD (NDN Forwarding Daemon).")
    
    try:
        run_sidecar(config_path)
    except KeyboardInterrupt:
        logger.info("Sidecar stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        logger.error("Container will keep running for debugging...")
        # Keep container alive for debugging (time is imported at module level)
        while True:
            time.sleep(60)
            logger.info("Container still running... (Ctrl+C to exit)")


if __name__ == '__main__':
    main()
