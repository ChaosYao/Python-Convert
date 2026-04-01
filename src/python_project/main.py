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

    _NDN_RESTART_DELAY_SEC = 3

    def run_ndn_server_thread():
        """
        Run NDN Server in a dedicated thread with automatic restart.

        python-ndn's run_forever() can return without raising an exception when
        the NFD connection is lost (e.g. resource exhaustion from an iptables
        redirect loop).  Without a restart loop the face and FIB entry are gone
        permanently, causing all subsequent Interests to receive NACK 150.

        This loop re-creates the NDNServer and re-registers the prefix every
        time run_forever() exits, giving the sidecar self-healing capability.
        """
        first_run = True
        while True:
            ndn_server: Optional[NDNServer] = None
            try:
                if first_run:
                    logger.info("NDN Server thread started")
                else:
                    logger.warning(
                        "NDN Server restarting after disconnect (delay=%ds)", _NDN_RESTART_DELAY_SEC
                    )

                ndn_server = NDNServer(pib_path=pib_path, tpm_path=tpm_path, config_path=config_path)

                if first_run:
                    ndn_server_holder["server"] = ndn_server
                    ndn_init_done.set()
                    logger.info("NDN Server initialized successfully")

                async def after_nfd_connected():
                    # Catch all unhandled Task exceptions so they appear in logs
                    # instead of being silently swallowed by asyncio.
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

                    # Periodic heartbeat: confirms the event loop is still running.
                    # If heartbeat logs stop appearing before run_forever() exits,
                    # the loop was blocked or stopped unexpectedly.
                    async def _heartbeat():
                        while True:
                            await asyncio.sleep(10)
                            pending = [t for t in asyncio.all_tasks() if not t.done()]
                            logger.debug(
                                "NDN event-loop heartbeat: alive prefix=%s pending_tasks=%d",
                                route_prefix, len(pending),
                            )
                    asyncio.create_task(_heartbeat(), name="ndn-heartbeat")

                ndn_server.app.run_forever(after_start=after_nfd_connected())

                # run_forever() returned — NDN app disconnected from NFD.
                # Face and FIB entries are now gone; the loop will restart.
                queued = ndn_server._bridge_executor._work_queue.qsize()
                active = len(ndn_server._bridge_executor._threads) \
                    if hasattr(ndn_server._bridge_executor, '_threads') else -1
                logger.error(
                    "NDN run_forever() EXITED (no exception) — face lost, prefix %s unregistered. "
                    "thread_pool: active=%d queued=%d. Restarting in %ds.",
                    route_prefix, active, queued, _NDN_RESTART_DELAY_SEC,
                )

            except Exception as e:
                if first_run:
                    ndn_init_done.set()
                logger.error("NDN Server error (will restart in %ds): %s", _NDN_RESTART_DELAY_SEC, e, exc_info=True)
            finally:
                if ndn_server:
                    try:
                        ndn_server.shutdown()
                    except Exception:
                        pass

            first_run = False
            time.sleep(_NDN_RESTART_DELAY_SEC)

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
        import time
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
        # Keep container alive for debugging
        import time
        while True:
            time.sleep(60)
            logger.info("Container still running... (Ctrl+C to exit)")


if __name__ == '__main__':
    main()
