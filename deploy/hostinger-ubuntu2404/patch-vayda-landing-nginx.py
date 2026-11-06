#!/usr/bin/env python3
"""Safely add or update the public landing-page locations in the HTTPS site."""

from __future__ import annotations

import re
import sys
from pathlib import Path

BEGIN_MARKER = "# BEGIN SMH VAYDA LANDING"
END_MARKER = "# END SMH VAYDA LANDING"
DOMAIN = "smartmoneyhub.tech"
WEB_ROOT = "/var/www/smartmoneyhub-ops"
LANDING_WEB_ROOT = "/var/www/_vayda_landing"


class ConfigError(RuntimeError):
    pass


def server_blocks(text: str) -> list[tuple[int, int, str]]:
    """Return complete top-level server blocks, ignoring braces in strings/comments."""
    blocks: list[tuple[int, int, str]] = []
    for match in re.finditer(r"(?m)^[ \t]*server[ \t]*\{", text):
        start = match.start()
        opening = text.find("{", match.start(), match.end())
        depth = 0
        quote: str | None = None
        escaped = False
        comment = False
        for index in range(opening, len(text)):
            char = text[index]
            if comment:
                if char == "\n":
                    comment = False
                continue
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char == "#":
                comment = True
            elif char in {"'", '"'}:
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    blocks.append((start, end, text[start:end]))
                    break
        else:
            raise ConfigError("An Nginx server block has unmatched braces.")
    return blocks


def render_locations(indent: str) -> str:
    inner = f"{indent}    "
    return "\n".join(
        [
            f"{indent}{BEGIN_MARKER}",
            f"{indent}location ^~ /_vayda_landing/ {{",
            f"{inner}root /var/www;",
            f"{inner}try_files $uri =404;",
            f'{inner}add_header Cache-Control "public, max-age=31536000, immutable";',
            f"{indent}}}",
            f"{indent}location = /robots.txt {{",
            f"{inner}root {LANDING_WEB_ROOT};",
            f"{inner}try_files /robots.txt =404;",
            f"{indent}}}",
            f"{indent}location = /sitemap.xml {{",
            f"{inner}root {LANDING_WEB_ROOT};",
            f"{inner}try_files /sitemap.xml =404;",
            f"{indent}}}",
            f"{indent}location = / {{",
            f"{inner}rewrite ^ /_vayda_landing/index.html last;",
            f"{indent}}}",
            f"{indent}location ~ ^/(about|education|market-analysis|philosophy|community|contact)(/|$) {{",
            f"{inner}return 302 /;",
            f"{indent}}}",
            f"{indent}location = /sign-up {{",
            f"{inner}return 302 /;",
            f"{indent}}}",
            f"{indent}location ^~ /sign-up/ {{",
            f"{inner}return 302 /;",
            f"{indent}}}",
            f"{indent}{END_MARKER}",
            "",
        ]
    )


def patch_text(text: str) -> str:
    candidates = []
    for start, end, block in server_blocks(text):
        has_domain = re.search(
            rf"(?m)^[ \t]*server_name[ \t]+[^;]*\b{re.escape(DOMAIN)}\b[^;]*;",
            block,
        )
        has_www = re.search(r"(?m)^[ \t]*server_name[ \t]+[^;]*\bwww\.smartmoneyhub\.tech\b[^;]*;", block)
        has_https = re.search(r"(?m)^[ \t]*listen[ \t]+443[ \t]+ssl(?:[ \t;]|$)", block)
        has_expected_root = re.search(
            rf"(?m)^[ \t]*root[ \t]+{re.escape(WEB_ROOT)}[ \t]*;",
            block,
        )
        if has_domain and has_www and has_https and has_expected_root:
            candidates.append((start, end, block))

    if len(candidates) != 1:
        raise ConfigError(
            "Expected exactly one HTTPS server block for smartmoneyhub.tech "
            "with the existing Operations Center web root; no changes made."
        )

    start, end, block = candidates[0]
    begin_count = block.count(BEGIN_MARKER)
    end_count = block.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ConfigError("The landing-page Nginx markers are incomplete or duplicated.")

    if begin_count == 1:
        begin = block.index(BEGIN_MARKER)
        begin_line = block.rfind("\n", 0, begin) + 1
        marker_end = block.index(END_MARKER, begin) + len(END_MARKER)
        end_line = block.find("\n", marker_end)
        end_line = len(block) if end_line < 0 else end_line + 1
        indent_match = re.match(r"[ \t]*", block[begin_line:])
        indent = indent_match.group(0) if indent_match else "    "
        updated_block = block[:begin_line] + render_locations(indent) + block[end_line:]
    else:
        if re.search(r"(?m)^[ \t]*location[ \t]+=[ \t]+/[ \t]*\{", block):
            raise ConfigError("The HTTPS site already has a root-only location; no changes made.")
        if re.search(r"(?m)^[ \t]*location[ \t]+\^~[ \t]+/_vayda_landing/", block):
            raise ConfigError("The landing asset path is already configured outside this installer.")
        if re.search(r"(?m)^[ \t]*location[ \t]+=[ \t]+/(?:robots\.txt|sitemap\.xml)[ \t]*\{", block):
            raise ConfigError("An SEO file route already exists outside this installer.")
        if re.search(r"(?m)^[ \t]*location[ \t]+(?:=[ \t]+)?/sign-up(?:/|\s|\{)", block):
            raise ConfigError("A sign-up Nginx route already exists; no changes made.")
        fallback = re.search(
            r"(?m)^(?P<indent>[ \t]*)location[ \t]+/[ \t]*\{",
            block,
        )
        if not fallback:
            raise ConfigError("The expected catch-all location / was not found; no changes made.")
        indent = fallback.group("indent")
        updated_block = (
            block[: fallback.start()]
            + render_locations(indent)
            + block[fallback.start() :]
        )

    return text[:start] + updated_block + text[end:]


def self_test() -> None:
    sample = """server {
    server_name smartmoneyhub.tech www.smartmoneyhub.tech;
    root /var/www/smartmoneyhub-ops;
    location = /api/healthz {
        return 200 '{"status":"ok"}';
    }
    location /api/ {
        proxy_pass http://127.0.0.1:23827;
    }
    location ^~ /operations {
        auth_basic "Smart Money Hub Operations";
        auth_basic_user_file /etc/nginx/.smh-ops-users;
        try_files $uri $uri/ /index.html;
    }
    location / {
        auth_basic off;
        try_files $uri $uri/ /index.html;
    }
    listen 443 ssl;
}
server {
    listen 80;
    server_name smartmoneyhub.tech www.smartmoneyhub.tech;
    return 301 https://$host$request_uri;
}
"""
    patched = patch_text(sample)
    assert patched.count(BEGIN_MARKER) == 1
    assert "auth_basic_user_file /etc/nginx/.smh-ops-users;" in patched
    assert "proxy_pass http://127.0.0.1:23827;" in patched
    assert "location = /sign-up {" in patched
    assert "location = /robots.txt {" in patched
    assert "root /var/www;" in patched
    assert "try_files $uri =404;" in patched
    assert "root /var/www/_vayda_landing;" in patched
    assert "rewrite ^ /_vayda_landing/index.html last;" in patched
    assert "location / {" in patched
    assert patch_text(patched) == patched


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        self_test()
        print("Nginx patch self-test passed.")
        return 0
    if len(sys.argv) != 3:
        print(
            f"Usage: {Path(sys.argv[0]).name} INPUT.conf OUTPUT.conf",
            file=sys.stderr,
        )
        return 2
    source, destination = map(Path, sys.argv[1:])
    try:
        updated = patch_text(source.read_text())
        destination.write_text(updated)
    except (OSError, ConfigError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
