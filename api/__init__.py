"""API handler registry.

Each module exports a `handle(handler, method, path) -> bool` function.
Modules are tried in order; first to return True wins.
"""
