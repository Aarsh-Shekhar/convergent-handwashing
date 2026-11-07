"""Live uvicorn server fixture for WebSocket tests (TestClient runs each websocket on its own
event loop, so cross-connection broadcasts cannot be exercised with it)."""

from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn

from convergent.backend.app import create_app
from convergent.common.config import Settings

TOKEN = "test-token-123"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    def __init__(self, db_url: str, token: str = TOKEN) -> None:
        self.port = free_port()
        self.app = create_app(Settings(api_token=token, database_url=db_url, log_dir="logs"), db_url)
        self.config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="on")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> LiveServer:
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc) -> None:  # type: ignore[no-untyped-def]
        self.server.should_exit = True
        self.thread.join(5)

    @property
    def http(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def ws(self) -> str:
        return f"ws://127.0.0.1:{self.port}"


@pytest.fixture
def live_server(tmp_path):
    with LiveServer(f"sqlite:///{tmp_path / 'live.db'}") as s:
        yield s
