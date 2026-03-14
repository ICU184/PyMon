"""Local HTTP callback server for EVE SSO OAuth2 flow.

Starts a lightweight HTTP server on localhost to receive the
OAuth2 authorization code callback from CCP's login server.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from pymon.core.config import SSO_CALLBACK_PORT

logger = logging.getLogger(__name__)

SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head><title>PyMon – Login Successful</title></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:sans-serif;
             display:flex;justify-content:center;align-items:center;height:100vh;margin:0">
    <div style="text-align:center">
        <h1 style="color:#4ecca3">✓ Login Successful</h1>
        <p>You can close this window and return to PyMon.</p>
    </div>
</body>
</html>
"""

FAILURE_HTML = """
<!DOCTYPE html>
<html>
<head><title>PyMon – Login Failed</title></head>
<body style="background:#1a1a2e;color:#e0e0e0;font-family:sans-serif;
             display:flex;justify-content:center;align-items:center;height:100vh;margin:0">
    <div style="text-align:center">
        <h1 style="color:#e74c3c">✗ Login Failed</h1>
        <p>An error occurred during login. Please try again.</p>
        <p style="color:#999">{error}</p>
    </div>
</body>
</html>
"""


@dataclass
class CallbackResult:
    """Result from the OAuth2 callback."""

    code: str
    state: str


class CallbackServer:
    """Local HTTP server that receives the EVE SSO OAuth2 callback."""

    def __init__(self) -> None:
        self._result_future: asyncio.Future[CallbackResult] | None = None
        self._server: asyncio.Server | None = None

    async def wait_for_callback(self, timeout: float = 120.0) -> CallbackResult:
        """Start server and wait for the OAuth2 callback.

        Args:
            timeout: Maximum seconds to wait for the callback.

        Returns:
            CallbackResult with the authorization code and state.

        Raises:
            TimeoutError: If no callback is received within timeout.
            ValueError: If the callback contains an error.
        """
        loop = asyncio.get_event_loop()
        self._result_future = loop.create_future()

        app = Starlette(routes=[
            Route("/callback", self._handle_callback, methods=["GET"]),
        ])

        import uvicorn

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=SSO_CALLBACK_PORT,
            log_level="warning",
            log_config=None,  # Disable uvicorn's logging config (fails in PyInstaller)
        )
        server = uvicorn.Server(config)

        # Run server in background
        server_task = asyncio.create_task(server.serve())

        try:
            result = await asyncio.wait_for(self._result_future, timeout=timeout)
            return result
        except TimeoutError:
            raise TimeoutError("SSO callback timed out after %d seconds" % int(timeout)) from None
        finally:
            server.should_exit = True
            await server_task

    async def _handle_callback(self, request: Request) -> HTMLResponse:
        """Handle the OAuth2 callback from EVE SSO."""
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            logger.error("SSO callback error: %s", error)
            if self._result_future and not self._result_future.done():
                self._result_future.set_exception(ValueError(f"SSO error: {error}"))
            return HTMLResponse(FAILURE_HTML.format(error=error), status_code=400)

        if not code or not state:
            logger.error("SSO callback missing code or state")
            if self._result_future and not self._result_future.done():
                self._result_future.set_exception(ValueError("Missing code or state"))
            return HTMLResponse(
                FAILURE_HTML.format(error="Missing authorization code"),
                status_code=400,
            )

        logger.info("Received SSO callback with code")
        if self._result_future and not self._result_future.done():
            self._result_future.set_result(CallbackResult(code=code, state=state))

        return HTMLResponse(SUCCESS_HTML)
