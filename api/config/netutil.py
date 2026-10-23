"""Outbound HTTPS for the few services we call (price feed, map lookup, message webhook).

Some Python installs (notably python.org builds on macOS) ship without a certificate store, so every https call fails verification.
certifi carries Mozilla's list, so these calls verify the same way everywhere.
"""
import ssl

import certifi


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())
