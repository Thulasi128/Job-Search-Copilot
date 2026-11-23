"""SSRF-safe web scraper for job descriptions using manual redirect validation and trafilatura."""

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse
from fastapi import HTTPException, status
import httpx
import trafilatura

logger = logging.getLogger(__name__)

MAX_REDIRECT_HOPS = 5
HTTP_TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB
MIN_EXTRACTED_JD_LENGTH = 200


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Determine whether an IP address belongs to private, loopback, link-local, or reserved networks.

    Args:
        ip: IPv4Address or IPv6Address instance.

    Returns:
        bool: True if the IP is blocked for SSRF safety, False if safe public IP.
    """
    # Check IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    ):
        return True

    # Explicit check for 0.0.0.0 and AWS metadata 169.254.169.254
    ip_str = str(ip)
    if ip_str == "0.0.0.0" or ip_str.startswith("169.254."):
        return True

    return False


def validate_url_and_resolve_ips(target_url: str) -> None:
    """Validate URL scheme and ensure all resolved DNS IP addresses are public and non-internal.

    Args:
        target_url: The URL to validate.

    Raises:
        ValueError: If scheme is not http/https or any resolved IP address is in a blocked range.
    """
    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}. Only HTTP and HTTPS are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL does not contain a valid hostname.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for hostname '{hostname}': {exc}")

    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        ip_obj = ipaddress.ip_address(ip_str)
        if is_ip_blocked(ip_obj):
            raise ValueError(f"Blocked IP address resolved for '{hostname}': {ip_str} (SSRF prevention)")


async def fetch_and_extract_url(url: str) -> str:
    """Fetch a public job description URL safely with SSRF protection, size limits, and trafilatura.

    Enforces:
      - http/https only
      - Manual redirect following (max 5 hops)
      - DNS IP address validation at each hop (blocks localhost, 10.x, 192.168.x, 169.254.x, etc.)
      - 10s request timeout
      - 2 MB stream response limit
      - Text/HTML content verification
      - Minimum ~200 characters extracted text

    Args:
        url: Public job posting URL.

    Returns:
        str: Extracted job description text.

    Raises:
        HTTPException: 422 if fetching fails or extracted text is under 200 characters.
    """
    current_url = url
    headers = {"User-Agent": "JobSearchCopilot/1.0 (+http://localhost:8000)"}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
            for hop in range(MAX_REDIRECT_HOPS):
                validate_url_and_resolve_ips(current_url)

                async with client.stream("GET", current_url, headers=headers) as response:
                    # Handle redirects manually
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            raise ValueError("Redirect response missing Location header.")
                        current_url = urljoin(current_url, location)
                        continue

                    if response.status_code != 200:
                        raise ValueError(f"HTTP request returned status {response.status_code}")

                    # Validate Content-Type
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and not (
                        "text/html" in content_type
                        or "text/plain" in content_type
                        or "application/xhtml" in content_type
                    ):
                        raise ValueError(f"Unsupported content type: {content_type}")

                    # Stream response enforcing 2 MB limit
                    body_chunks = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > MAX_RESPONSE_SIZE_BYTES:
                            raise ValueError("Response exceeded 2 MB size limit.")
                        body_chunks.append(chunk)

                    raw_html = b"".join(body_chunks).decode("utf-8", errors="replace")
                    extracted_text = trafilatura.extract(
                        raw_html,
                        include_comments=False,
                        include_tables=True,
                        no_fallback=False,
                    )

                    if not extracted_text or len(extracted_text.strip()) < MIN_EXTRACTED_JD_LENGTH:
                        # Fallback to plain text if trafilatura stripped too much
                        if len(raw_html.strip()) >= MIN_EXTRACTED_JD_LENGTH and "text/plain" in content_type:
                            extracted_text = raw_html.strip()
                        else:
                            raise ValueError("Extracted text is under 200 characters.")

                    return extracted_text.strip()

            raise ValueError("Too many redirect hops (exceeded limit of 5).")

    except Exception as exc:
        logger.warning("URL fetching or extraction failed for %s: %s", url, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Could not extract a readable job description from the provided URL ({str(exc)}). "
                "Please copy and paste the job description text directly."
            ),
        )

