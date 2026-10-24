"""Malformed authorization must not disconnect the local API request."""
import json
from http.client import HTTPConnection

import pytest

from autodub.openclaw_runtime import OpenClawRuntime


@pytest.mark.parametrize("authorization", ["Bearer caf\xe9", "Bearer wrong", "", "Basic wrong"])
def test_invalid_authorization_returns_401(tmp_path, authorization):
    runtime = OpenClawRuntime(data_dir=tmp_path)
    runtime.start(worker=False)
    connection = HTTPConnection(*runtime._server.server_address, timeout=3)
    try:
        connection.request("GET", "/health", headers={"Authorization": authorization})
        response = connection.getresponse()
        assert response.status == 401
        assert json.loads(response.read())["ok"] is False
    finally:
        connection.close()
        runtime.stop()
