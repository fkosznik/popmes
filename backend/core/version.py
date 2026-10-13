from pathlib import Path


def app_version() -> str:
    """Read the application version shipped with this build.

    The image stores VERSION next to the application. A source checkout
    keeps that file in the repository root, outside the backend directory.
    Nothing is fetched from Git or from the current branch name.
    """
    here = Path(__file__).resolve()
    candidates = [here.parents[1] / "VERSION", here.parents[2] / "VERSION"]
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        version = text.strip().split()[0] if text.strip() else ""
        if version:
            return version
    return ""
