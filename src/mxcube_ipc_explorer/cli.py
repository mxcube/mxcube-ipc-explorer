"""Entry point: parses connection settings and runs the TUI app."""

from __future__ import annotations

import argparse

from mxcube_ipc_explorer.app import MXCuBEIPCExplorerApp
from mxcube_ipc_explorer.logging_config import configure_logging, logger


def run() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__ or "mxcube-ipc-explorer",
    )
    parser.add_argument("--token", required=True, help="IPCServer auth_token")
    parser.add_argument("--transport", choices=["jsonrpc", "nanomq"], default="jsonrpc")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--broker-host", default="localhost")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--topic-prefix", default="mxcube/ipc")
    parser.add_argument(
        "--log-file",
        default="mxcube-ipc-explorer.log",
        help="every request and every exception/error is logged here "
        "(default: %(default)s)",
    )

    args = parser.parse_args()

    configure_logging(args.log_file)
    logger.info("=== mxcube-ipc-explorer starting (log file: %s) ===", args.log_file)

    if args.transport == "jsonrpc":
        client_kwargs = {"token": args.token, "transport": "jsonrpc", "host": args.host, "port": args.port}
    else:
        client_kwargs = {
            "token": args.token,
            "transport": "nanomq",
            "broker_host": args.broker_host,
            "broker_port": args.broker_port,
            "topic_prefix": args.topic_prefix,
        }

    try:
        MXCuBEIPCExplorerApp(client_kwargs, log_file=args.log_file).run()
    finally:
        logger.info("=== mxcube-ipc-explorer exiting ===")


if __name__ == "__main__":
    run()
