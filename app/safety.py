"""SSRF protection: only public http/https destinations are allowed."""
import ipaddress, os, socket
from urllib.parse import urlparse

class UnsafeURL(ValueError):
    pass

def validate_url(url: str) -> str:
    try:
        p = urlparse((url or "").strip())
        port = p.port
    except ValueError as e:
        raise UnsafeURL("URL contains an invalid host or port.") from e
    if p.scheme not in ("http", "https") or not p.hostname:
        raise UnsafeURL("Only http and https URLs with a host are allowed.")
    if p.username or p.password:
        raise UnsafeURL("URLs with embedded credentials are not allowed.")
    if os.environ.get("ALLOW_PRIVATE") == "1":  # tests/demo only
        return p.geturl()
    try:
        infos = socket.getaddrinfo(p.hostname, port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise UnsafeURL("Host cannot be resolved.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:  # private, loopback, link-local, metadata (169.254.x) ...
            raise UnsafeURL("Destination is not a public address.")
    return p.geturl()
