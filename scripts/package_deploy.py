"""Build deployment ZIPs exclusively from a committed git archive and an allowlist."""

import argparse
import io
import json
from pathlib import Path
import subprocess
import zipfile

APP_FILES = {"app.py", "agent.py", "agent.md", "memory.md", "requirements.txt"}
ROUTER_FILES = {"router/router.py", "router/config.json"}


def build(kind, output, ref="HEAD", pct=0):
    if kind not in ("app", "router"):
        raise ValueError("kind must be app or router")
    files = APP_FILES if kind == "app" else ROUTER_FILES
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], text=True
    ).strip()
    archive = subprocess.check_output(["git", "archive", "--format=zip", revision, *sorted(files)])
    from router.router import validar_config, validar_pct
    validar_pct(pct)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        if set(source.namelist()) - {"router/"} != files:
            raise ValueError("archive is missing required deployment files")
        content = {name: source.read(name) for name in files}
    if kind == "router":
        config = json.loads(content["router/config.json"])
        config["pct"] = pct
        content["router/config.json"] = json.dumps(validar_config(config)).encode()
        content = {Path(name).name: data for name, data in content.items()}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in sorted(content.items()):
            package.writestr(name, data)
    with zipfile.ZipFile(output) as package:
        expected = APP_FILES if kind == "app" else {"router.py", "config.json"}
        if set(package.namelist()) != expected or package.testzip():
            raise ValueError("unsafe or corrupt deployment archive")
    print(f"Verified {kind} package from {revision}: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["app", "router"])
    parser.add_argument("output")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--pct", type=float, default=0)
    args = parser.parse_args()
    build(args.kind, args.output, args.ref, args.pct)
