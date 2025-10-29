import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import bcrypt
import jwt


class AuthError(Exception):
    """Raised when authentication or token validation fails."""


class AuthManager:
    def __init__(
        self,
        password_hash: str,
        token_secret: Optional[str],
        token_ttl_seconds: int = 3600,
        issuer: str = "eris",
    ) -> None:
        self.password_hash = password_hash or ""
        self.token_secret = token_secret or secrets.token_urlsafe(48)
        self.token_ttl = max(int(token_ttl_seconds), 300)
        self.issuer = issuer

    def verify_password(self, password: str) -> bool:
        if not self.password_hash:
            raise AuthError("Password hash not configured.")
        try:
            return bool(
                bcrypt.checkpw(password.encode("utf-8"), self.password_hash.encode("utf-8"))
            )
        except ValueError as exc:  # pragma: no cover - defensive
            raise AuthError("Invalid password hash configuration.") from exc

    def issue_token(self, subject: str = "admin") -> Dict[str, object]:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=self.token_ttl)
        payload = {
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "iss": self.issuer,
        }
        token = jwt.encode(payload, self.token_secret, algorithm="HS256")
        return {"token": token, "expires_at": expires.isoformat(), "expires_in": self.token_ttl}

    def verify_token(self, token: str) -> Dict[str, object]:
        try:
            payload = jwt.decode(
                token,
                self.token_secret,
                algorithms=["HS256"],
                options={"require": ["exp", "iat", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("Token expired.") from exc
        except jwt.InvalidTokenError as exc:  # pragma: no cover - defensive
            raise AuthError("Invalid token.") from exc

        if payload.get("iss") != self.issuer:
            raise AuthError("Invalid token issuer.")
        return payload
