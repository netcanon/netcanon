"""
Netcanon Desktop — Windows desktop shell for the Netcanon web application.

This package wraps the ``netcanon`` FastAPI application in a native Windows
desktop experience:

* An embedded Edge/WebView2 window shows the full web UI.
* A system tray icon provides Show and Quit actions when the window is hidden.
* The Uvicorn HTTP server runs on a loopback port in a daemon thread.

Entry point::

    python -m netcanon_desktop          # launch the desktop application

Build MSI installer::

    python setup_desktop.py bdist_msi

See ``netcanon_desktop/README.md`` for architecture details.
"""

__version__ = "0.1.0"
