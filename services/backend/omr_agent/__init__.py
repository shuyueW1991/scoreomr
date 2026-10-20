"""Backward-compatible OMR core.

The package started as a research prototype (``omr_agent``) and is kept as a
plain, importable library: preprocess -> engines -> metrics -> play -> select.
The web service only adds queueing and storage around it.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("scoreomr")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.1.0"
