"""Uvicorn server runner for the Agent OS Web UI."""

import logging

import uvicorn

from agent_os.kernel.master_kernel import AgentOSKernel
from agent_os.web.app import create_web_app

logger = logging.getLogger(__name__)


def run_web_server(
    kernel: AgentOSKernel,
    host: str = "127.0.0.1",
    port: int = 3000,
    log_level: str = "info",
) -> None:
    """Launch the Agent OS Web UI HTTP server using Uvicorn.

    Args:
        kernel: Initialized AgentOSKernel runtime.
        host: Host binding interface (default: 127.0.0.1).
        port: Port binding (default: 3000).
        log_level: Uvicorn log level.
    """
    app = create_web_app(kernel)
    logger.info("Starting Agent OS Web UI on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level=log_level)
