"""Bounded health checks and router deployment; publish credentials stay in memory."""

import argparse
import base64
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid
import xml.etree.ElementTree as ET

from router.router import validar_pct, validar_url
from scripts.package_deploy import build


def integer(value, minimum, maximum):
    result = int(value)
    if str(result) != str(value) or not minimum <= result <= maximum:
        raise ValueError(f"expected integer between {minimum} and {maximum}")
    return result


def read(url, **kwargs):
    request = urllib.request.Request(url, **kwargs)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(), response.headers


def health(url, attempts=18):
    url = validar_url(url)
    attempts = integer(attempts, 1, 30)
    for attempt in range(attempts):
        try:
            body, _ = read(url + "/_stcore/health")
            if body.strip() == b"ok":
                return
        except (OSError, urllib.error.URLError):
            pass
        if attempt + 1 < attempts:
            time.sleep(10)
    raise RuntimeError("Streamlit health check failed")


def observe(url, minutes):
    url = validar_url(url)
    minutes = integer(minutes, 1, 60)
    deadline = time.monotonic() + minutes * 60
    while True:
        health(url, 1)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(30, remaining))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def publish_router(pct):
    validar_pct(pct)
    router_url = validar_url(os.environ["ROUTER_URL"])
    router_host = urlsplit(router_url).hostname
    if not router_host.endswith(".azurewebsites.net"):
        raise ValueError("router must use its Azure default hostname")
    expected_scm = router_host.removesuffix(".azurewebsites.net") + ".scm.azurewebsites.net"
    profiles = ET.fromstring(os.environ["ROUTER_PUBLISH_PROFILE"])
    profile = next((p for p in profiles.iter("publishProfile")
                    if p.get("publishMethod") == "ZipDeploy"), None)
    if profile is None:
        raise ValueError("ZipDeploy publish profile required")
    publish_host = profile.get("publishUrl", "")
    parsed = urlsplit("https://" + publish_host)
    if (parsed.hostname != expected_scm or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("publish profile does not belong to router")
    user, password = profile.get("userName"), profile.get("userPWD")
    if not user or not password:
        raise ValueError("publish profile credentials missing")
    headers = {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{password}".encode()).decode(), "Content-Type": "application/zip"}
    package = Path(".canary-build") / f"router-{uuid.uuid4().hex}.zip"
    try:
        build("router", package, pct=pct)
        opener = urllib.request.build_opener(NoRedirect())
        request = urllib.request.Request(
            f"https://{expected_scm}/api/zipdeploy?isAsync=true",
            data=package.read_bytes(), headers=headers, method="POST")
        with opener.open(request, timeout=120) as response:
            location = response.headers.get("Location")
        if not location:
            raise RuntimeError("SCM did not return deployment status URL")
        status_url = urlsplit(location)
        if (status_url.scheme != "https" or status_url.hostname != expected_scm
                or status_url.port not in (None, 443) or status_url.username
                or status_url.password):
            raise ValueError("unexpected SCM status URL")
        for _ in range(120):
            request = urllib.request.Request(location, headers=headers)
            with opener.open(request, timeout=30) as response:
                status = json.load(response).get("status")
            if status == 4:
                break
            if status == 3:
                raise RuntimeError("router deployment failed")
            time.sleep(5)
        else:
            raise RuntimeError("router deployment timed out")
        for _ in range(36):
            try:
                body, _ = read(router_url + "/_router/status")
                if json.loads(body)["pct"] == pct:
                    return
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(5)
        raise RuntimeError("router did not confirm requested percentage")
    finally:
        package.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    publish = subs.add_parser("publicar-router")
    publish.add_argument("pct", type=float)
    check = subs.add_parser("saude")
    check.add_argument("url")
    check.add_argument("attempts", nargs="?", default="18")
    watch = subs.add_parser("observar")
    watch.add_argument("url")
    watch.add_argument("minutes")
    args = parser.parse_args()
    try:
        if args.command == "publicar-router":
            publish_router(args.pct)
        elif args.command == "saude":
            health(args.url, args.attempts)
        else:
            observe(args.url, args.minutes)
    except Exception as exc:
        # Never emit credentials, XML, response bodies or authenticated request objects.
        parser.exit(1, f"Canary operation failed ({type(exc).__name__}); check configuration/service health.\n")


if __name__ == "__main__":
    main()
