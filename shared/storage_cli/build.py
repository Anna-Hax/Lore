"""Build the pinned official CLI with Lore's stdin-key entrypoint.

No source edits to the SDK/CLI implementation; only main.go is replaced.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REVISION = "bb5675461a96b654d3015c5522666ee8101cf810"
HERE = Path(__file__).resolve().parent


def build(source: str, output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lore-storage-build-") as temporary:
        checkout = Path(temporary) / "source"
        subprocess.run(["git", "clone", "--no-hardlinks", source, str(checkout)], check=True)
        subprocess.run(["git", "checkout", "--detach", REVISION], cwd=checkout, check=True)
        shutil.copyfile(HERE / "main.go", checkout / "main.go")
        environment = dict(os.environ)
        environment.setdefault("GOCACHE", "/tmp/lore-go-build-cache")
        environment.setdefault("GOMODCACHE", "/tmp/lore-go-mod-cache")
        subprocess.run(["go", "build", "-trimpath", "-o", str(output), "."], cwd=checkout, env=environment, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="https://github.com/0gfoundation/0g-storage-client.git")
    parser.add_argument("--output", type=Path, default=HERE / "bin/lore-storage-client")
    args = parser.parse_args()
    build(args.source, args.output)
