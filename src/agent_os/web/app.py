"""ASGI application factory for the Agent OS Web interface."""

from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from agent_os.kernel.master_kernel import AgentOSKernel
from agent_os.web.routes import build_api_routes


def create_web_app(kernel: AgentOSKernel) -> Starlette:
    """Create and configure the Starlette application for Agent OS.

    Args:
        kernel: Initialized AgentOSKernel runtime.

    Returns:
        Configured Starlette ASGI application.
    """
    static_dir = Path(__file__).parent / "static"
    index_file = static_dir / "index.html"

    async def serve_index(_request: Request) -> Response:
        if index_file.exists():
            return FileResponse(index_file)
        return Response("Agent OS Web UI static files not found.", status_code=404)

    api_routes = build_api_routes(kernel)
    routes: list[BaseRoute] = [
        Route("/", serve_index, methods=["GET"]),
        *api_routes,
    ]

    if static_dir.exists():
        routes.append(Mount("/static", app=StaticFiles(directory=str(static_dir)), name="static"))

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    return Starlette(routes=routes, middleware=middleware)
