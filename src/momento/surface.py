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
    raise NotImplementedError("surface.detect_surface")
