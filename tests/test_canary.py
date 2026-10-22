import io
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import zipfile

import pytest

from router import router
from scripts import canary, package_deploy


@pytest.mark.parametrize("pct", [-1, 101, float("nan"), float("inf"), True, "10", None])
def test_invalid_percentage(pct):
    with pytest.raises(ValueError):
        router.escolher_destino(pct, None, 0.5)


def test_routing_boundaries_and_stickiness():
    assert router.escolher_destino(0, "canary", 0) == "estavel"
    assert router.escolher_destino(100, "estavel", 0.99) == "canary"
    assert router.escolher_destino(10, "estavel", 0) == "estavel"
    assert router.escolher_destino(10, "canary", 0.99) == "canary"
    assert router.escolher_destino(10, "invalid", 0.099) == "canary"
    assert router.escolher_destino(10, None, 0.1) == "estavel"


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pw@example.com",
                               "https://example.com/path", "https://example.com?x=1",
                               "https://example.com\r\nX:bad", "https://", None])
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        router.validar_url(url)


@pytest.mark.parametrize("config", [{}, [], {"pct": 1, "urls": {}},
                                  {"pct": 0, "urls": {"estavel": "https://x", "canary": "https://x"}}])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        router.validar_config(config)


def test_http_status_redirect_head_and_bad_configuration(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    data = {"pct": 100, "urls": {"estavel": "https://stable.example",
                               "canary": "https://canary.example"}}
    config.write_text(json.dumps(data))
    monkeypatch.setattr(router, "CONFIG_JSON", config)
    server = ThreadingHTTPServer(("127.0.0.1", 0), router.Roteador)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    connection = HTTPConnection(*server.server_address, timeout=5)
    try:
        connection.request("GET", "/hello?q=a", headers={"Cookie": "versao=estavel"})
        response = connection.getresponse()
        assert response.status == 302
        assert response.getheader("Location") == "https://canary.example/hello?q=a"
        assert "Secure; HttpOnly; SameSite=Lax" in response.getheader("Set-Cookie")
        assert response.getheader("Cache-Control") == "no-store"
        response.read()
        connection.request("GET", "/_router/status")
        response = connection.getresponse()
        assert json.loads(response.read()) == data
        connection.request("HEAD", "/")
        response = connection.getresponse()
        assert response.status == 302
        assert response.read() == b""
        config.write_text('{"pct":NaN}')
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 503
        response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("kind", ["app", "router"])
def test_archive_allowlist(kind, tmp_path, monkeypatch):
    names = package_deploy.APP_FILES if kind == "app" else package_deploy.ROUTER_FILES
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name in names:
            value = router.CONFIG_JSON.read_bytes() if name.endswith("config.json") else b"source"
            z.writestr(name, value)
    calls = []

    def git(args, **kwargs):
        calls.append(args)
        return "abc123\n" if "rev-parse" in args else archive.getvalue()

    monkeypatch.setattr(package_deploy.subprocess, "check_output", git)
    output = tmp_path / "deploy.zip"
    package_deploy.build(kind, output, pct=100)
    with zipfile.ZipFile(output) as z:
        assert not any(".env" in name for name in z.namelist())
        assert set(z.namelist()) == (names if kind == "app" else {"router.py", "config.json"})
        if kind == "router":
            assert json.loads(z.read("config.json"))["pct"] == 100
    assert calls[1][:4] == ["git", "archive", "--format=zip", "abc123"]


def test_health_is_bounded_and_requires_ok(monkeypatch):
    calls = []
    monkeypatch.setattr(canary, "read", lambda url: (calls.append(url) or b"not ok", {}))
    monkeypatch.setattr(canary.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError):
        canary.health("https://stable.example", 2)
    assert len(calls) == 2
    monkeypatch.setattr(canary, "read", lambda _: (b"ok", {}))
    canary.health("https://stable.example", 1)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "nan", "61", "01", "x"])
def test_invalid_observation_duration(value):
    with pytest.raises(ValueError):
        canary.integer(value, 1, 60)


def test_profile_host_mismatch_rejected_before_network(monkeypatch):
    monkeypatch.setenv("ROUTER_URL", "https://venanx-3aier-agents-router.azurewebsites.net")
    monkeypatch.setenv("ROUTER_PUBLISH_PROFILE",
                       '<publishData><publishProfile publishMethod="ZipDeploy" '
                       'publishUrl="evil.example" userName="x" userPWD="secret"/></publishData>')
    with pytest.raises(ValueError, match="does not belong"):
        canary.publish_router(10)


def test_router_publication_polls_and_cleans_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ROUTER_URL", "https://test-router.azurewebsites.net")
    monkeypatch.setenv("ROUTER_PUBLISH_PROFILE",
                       '<publishData><publishProfile publishMethod="ZipDeploy" '
                       'publishUrl="test-router.scm.azurewebsites.net:443" '
                       'userName="test" userPWD="not-a-real-secret"/></publishData>')
    seen = []

    class Response(io.BytesIO):
        headers = {"Location": "https://test-router.scm.azurewebsites.net/api/deployments/test"}

    class Opener:
        def open(self, request, timeout):
            seen.append(request)
            assert timeout <= 120
            return Response(b'{"status":4}')

    def build(kind, output, **kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"zip")

    monkeypatch.setattr(canary, "build", build)
    monkeypatch.setattr(canary.urllib.request, "build_opener", lambda _: Opener())
    monkeypatch.setattr(canary, "read", lambda _: (b'{"pct":100}', {}))
    canary.publish_router(100)
    assert len(seen) == 2
    assert seen[0].method == "POST"
    assert not list((tmp_path / ".canary-build").glob("*.zip"))


def test_archive_rejects_unexpected_secret_file(tmp_path, monkeypatch):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name in package_deploy.APP_FILES | {".env"}:
            z.writestr(name, "not-a-secret")
    monkeypatch.setattr(package_deploy.subprocess, "check_output",
                        lambda args, **kwargs: "abc\n" if "rev-parse" in args else archive.getvalue())
    with pytest.raises(ValueError, match="archive"):
        package_deploy.build("app", tmp_path / "bad.zip")
    assert not (tmp_path / "bad.zip").exists()
