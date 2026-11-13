"""Run the fixed research code in a separate, bounded Python 3.12 process."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import resource
import sys


def main() -> int:
    resource.setrlimit(resource.RLIMIT_CPU, (75, 80))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3,) * 2)
    tools, industry, config, cache, membership, output = sys.argv[1:]
    requirements = Path(tools) / "requirements-sector-strategies.txt"
    try:
        if sys.version_info[:2] != (3, 12) or any(
            version(name) != expected
            for name, expected in (line.split("==") for line in requirements.read_text().splitlines() if line.strip())
        ):
            return 2
        sys.path.insert(0, tools)
        from train_joint import replay_saved
    except (ImportError, PackageNotFoundError, FileNotFoundError):
        return 2
    replay_saved(industry, Path(config), Path(cache), Path(membership), Path(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
