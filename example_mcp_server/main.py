import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import click

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent
import mcp.types as types

from paylink.mcp.monetize_mcp import require_payment
from paylink.mcp.wallet_context import set_agent_wallet_from_scope, reset_agent_wallet

load_dotenv()

logger = logging.getLogger(__name__)


@click.command()
@click.option("--port", default=5003, help="Port to listen on for HTTP")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
@click.option(
    "--json-response",
    is_flag=True,
    default=False,
    help="Enable JSON responses for StreamableHTTP",
)
def main(
    port: int | None = None,
    log_level: str | None = None,
    json_response: bool | None = None,
) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = Server("example-mcp-server")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="add",
                description="Add two integers",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            ),
            types.Tool(
                name="subtract",
                description="Subtract two integers",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            ),
        ]

    @app.call_tool()
    @require_payment(
            {
            "add": {
                "base_cost": 0.10,
                "require_evaluation": True,
            },
            "subtract": {
                "base_cost": 0.10,
                "require_evaluation": True,
            },
        }
    )
    async def call_tool(tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if tool_name == "add":
            result = arguments["a"] + arguments["b"]
            return [types.TextContent(type="text", text=str(result))]
        elif tool_name == "subtract":
            result = arguments["a"] - arguments["b"]
            return [types.TextContent(type="text", text=str(result))]
        else:
            return [
                types.TextContent(
                    type="text", text=f"Error: Unknown tool '{tool_name}'"
                )
            ]

    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,
        json_response=json_response,
        stateless=True,
    )

    async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send
    ) -> None:
        # sets wallet into request context variable
        token = set_agent_wallet_from_scope(scope)

        try:
            await session_manager.handle_request(scope, receive, send)
        except Exception:
            logger.exception("Streamable HTTP error")
        finally:
            reset_agent_wallet(token)

    @contextlib.asynccontextmanager
    async def lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    routes = [
        Mount("/mcp", app=handle_streamable_http),
    ]

    starlette_app = Starlette(debug=True, lifespan=lifespan, routes=routes)
    uvicorn.run(starlette_app, host="0.0.0.0", port=port, log_level=log_level.lower())


if __name__ == "__main__":
    main()
