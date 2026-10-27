"""Bounded public HTTPS source download for OCR fallback, with DNS pinning."""
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import httpx


def download_public_ocr_source(url: str, destination: Path, *, max_bytes: int = 200 * 1024 * 1024) -> Path:
    with httpx.Client(trust_env=False, timeout=60, follow_redirects=False) as client:
        for _ in range(6):
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                raise ValueError("OCR_SOURCE_URL_INVALID")
            addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
            ips = [str(item[4][0]) for item in addresses]
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise ValueError("OCR_SOURCE_URL_NOT_PUBLIC")
            # Connect to the checked address, while preserving TLS SNI and HTTP Host.
            original = httpx.URL(url)
            pinned = original.copy_with(host=ips[0])
            with client.stream("GET", pinned, headers={"Host": parts.netloc}, extensions={"sni_hostname": parts.hostname}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                size = 0
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("OCR_SOURCE_TOO_LARGE")
                        handle.write(chunk)
                if not size:
                    raise ValueError("OCR_SOURCE_EMPTY")
                return destination
    raise ValueError("OCR_SOURCE_TOO_MANY_REDIRECTS")
