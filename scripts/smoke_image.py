"""Exercise the shipped non-root image with a synthetic EPUB; remove test containers."""

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request


def docker(*args, data=None):
    return subprocess.check_output(["docker", *args], input=data, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    image = parser.parse_args().image
    epub = docker(
        "run",
        "--rm",
        "-i",
        "--entrypoint",
        "pandoc",
        image,
        "--from=markdown",
        "--to=epub",
        "--metadata=title:Smoke Book",
        data=b"# Smoke Book\n\nA synthetic conversion check.\n",
    )
    container = (
        docker(
            "run",
            "--detach",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,noexec,size=256m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--publish",
            "127.0.0.1::3000",
            image,
        )
        .decode()
        .strip()
    )
    try:
        config = json.loads(docker("inspect", container))[0]
        assert config["Config"]["User"] == "10001:10001", "Expected unprivileged runtime"
        port = config["NetworkSettings"]["Ports"]["3000/tcp"][0]["HostPort"]
        base = "http://127.0.0.1:" + port
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as response:
                    assert json.load(response)["status"] == "ok"
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Container did not become healthy") from None
                time.sleep(0.2)
        request = urllib.request.Request(
            base + "/convert", data=epub, headers={"Content-Type": "application/epub+zip"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.headers["X-Conversion-Pipeline"] == "reading-markdown-v1"
            assert "A synthetic conversion check." in response.read().decode()
        print(
            json.dumps(
                {
                    "imageSmoke": True,
                    "nonRoot": True,
                    "readOnlyRoot": True,
                    "health": True,
                    "epubConversion": True,
                }
            )
        )
    finally:
        docker("rm", "--force", container)


if __name__ == "__main__":
    main()
