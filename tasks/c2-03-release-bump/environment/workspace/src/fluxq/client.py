"""Queue client; the user agent carries the package version."""

from fluxq import __version__

USER_AGENT = f"fluxq/{__version__}"
