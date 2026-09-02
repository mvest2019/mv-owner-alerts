# -*- coding: utf-8 -*-
"""Vercel entry point.

Vercel's Python runtime looks for a module-level `handler` that subclasses
BaseHTTPRequestHandler, which is exactly the shape server.py already has - so this file only
puts the project root on sys.path and re-exports it. server.main() is never called: Vercel owns
the socket, and the local-only parts of it (webbrowser.open, the config banner) have no meaning
here.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import Handler as handler  # noqa: E402,F401
