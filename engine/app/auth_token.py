"""auth_token — mint a service token from the shell.

    python -m app.auth_token            # prints a freshly minted HS256 token
    python -m app.auth_token my-service # optional subject

Reads the same `JWT_*` environment config the engine verifies against
(`AuthConfig.from_env()`), so the printed token is accepted by a running engine
with the same secret. There is intentionally no login flow and no public
token-minting HTTP endpoint (ADR 0005); this CLI (wired as `make token`) is the
only mint path.
"""
from __future__ import annotations

import sys

from app.auth import AuthConfig, mint_token


def main(argv: list) -> int:
    subject = argv[1] if len(argv) > 1 else "jarvis-service"
    try:
        token = mint_token(AuthConfig.from_env(), subject=subject)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
