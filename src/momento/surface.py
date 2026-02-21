"""Surface detection from working directory path."""


def detect_surface(cwd: str) -> str | None:
    """Detect development surface from current working directory.

    Matches on directory boundaries (not substrings):
    - /server or /backend -> "server"
    - /web or /frontend -> "web"
    - /ios -> "ios"
    - /android -> "android"
    - none of the above -> None

    Case-insensitive. /Server and /server both match.
    Directory-boundary aware: /observer does NOT match server.
    """
    if not cwd or cwd == "/":
        return None

    # Map of exact directory names to surface identifiers
    surface_map = {
        "server": "server",
        "backend": "server",
        "web": "web",
        "frontend": "web",
        "ios": "ios",
        "android": "android",
    }

    for segment in cwd.split("/"):
        match = surface_map.get(segment.lower())
        if match is not None:
            return match

    return None
