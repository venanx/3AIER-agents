"""Redirect-only canary entry point; no model calls or third-party dependencies."""

import json
import math
import os
import random
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_JSON = Path(__file__).with_name("config.json")
DESTINOS = ("estavel", "canary")
COOKIE = "versao"


def validar_pct(pct):
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise ValueError("pct must be a number")
    if not math.isfinite(pct) or not 0 <= pct <= 100:
        raise ValueError("pct must be finite and between 0 and 100")
    return pct


def validar_url(url):
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("URL must be an HTTPS origin")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError("URL must be an HTTPS origin")
    return url.rstrip("/")


def validar_config(config):
    if not isinstance(config, dict) or set(config) != {"pct", "urls"}:
        raise ValueError("config requires pct and urls")
    validar_pct(config["pct"])
    if not isinstance(config["urls"], dict) or set(config["urls"]) != set(DESTINOS):
        raise ValueError("urls requires estavel and canary")
    for url in config["urls"].values():
        validar_url(url)
    if config["urls"]["estavel"].rstrip("/") == config["urls"]["canary"].rstrip("/"):
        raise ValueError("stable and canary must differ")
    return config


def carregar_config():
    return validar_config(json.loads(CONFIG_JSON.read_text(encoding="utf-8")))


def escolher_destino(pct, cookie, sorteio):
    validar_pct(pct)
    if not 0 <= sorteio < 1:
        raise ValueError("draw must be in [0, 1)")
    if pct == 0:
        return "estavel"
    if pct == 100:
        return "canary"
    if cookie in DESTINOS:
        return cookie
    return "canary" if sorteio < pct / 100 else "estavel"


class Roteador(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            config = carregar_config()
        except (OSError, ValueError, TypeError):
            self.send_error(503, "Invalid router configuration")
            return
        if self.path == "/_router/status":
            body = json.dumps(config).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        if not self.path.startswith("/") or any(ord(c) < 32 for c in self.path):
            self.send_error(400, "Invalid request target")
            return
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            cookie = cookies[COOKIE].value if COOKIE in cookies else None
        except CookieError:
            cookie = None
        destino = escolher_destino(config["pct"], cookie, random.random())
        self.send_response(302)
        self.send_header("Location", config["urls"][destino].rstrip("/") + self.path)
        self.send_header("Set-Cookie",
                         f"{COOKIE}={destino}; Max-Age=3600; Path=/; Secure; HttpOnly; SameSite=Lax")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    carregar_config()  # Fail startup explicitly instead of silently routing invalid settings.
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8000"))), Roteador).serve_forever()
