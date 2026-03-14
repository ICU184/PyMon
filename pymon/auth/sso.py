"""EVE SSO OAuth2 authentication with PKCE flow.

Implements the modern EVE SSO flow:
1. Generate PKCE code_verifier + code_challenge
2. Open browser to CCP's login page
3. Local callback server receives auth code
4. Exchange auth code for access + refresh tokens
5. Validate JWT token and extract character info
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import webbrowser
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from pymon.core.config import (
    ESI_AUTH_URL,
    ESI_JWKS_URL,
    ESI_TOKEN_URL,
    SSO_CALLBACK_URL,
)

logger = logging.getLogger(__name__)


@dataclass
class SSOResult:
    """Result of a successful SSO authentication."""

    character_id: int
    character_name: str
    access_token: str
    refresh_token: str
    expires_in: int
    scopes: list[str]


class EVEAuth:
    """Handles EVE SSO OAuth2 authentication using PKCE flow."""

    def __init__(self, client_id: str, scopes: list[str]) -> None:
        self.client_id = client_id
        self.scopes = scopes
        self._code_verifier: str = ""
        self._state: str = ""

    def generate_auth_url(self) -> str:
        """Generate the SSO authorization URL with PKCE challenge.

        Returns:
            The URL to open in the user's browser.
        """
        # Generate PKCE code verifier (43-128 characters)
        self._code_verifier = secrets.token_urlsafe(32)

        # Generate code challenge (S256)
        digest = hashlib.sha256(self._code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        # Generate state for CSRF protection
        self._state = secrets.token_urlsafe(16)

        params = {
            "response_type": "code",
            "redirect_uri": SSO_CALLBACK_URL,
            "client_id": self.client_id,
            "scope": " ".join(self.scopes),
            "state": self._state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        url = f"{ESI_AUTH_URL}?{urlencode(params)}"
        logger.debug("Generated auth URL: %s", url)
        return url

    def open_browser_login(self) -> str:
        """Open the browser for SSO login.

        Returns:
            The state parameter for verification.
        """
        url = self.generate_auth_url()
        webbrowser.open(url)
        logger.info("Opened browser for SSO login")
        return self._state

    async def exchange_code(self, code: str, state: str) -> SSOResult:
        """Exchange authorization code for tokens.

        Args:
            code: The authorization code from the callback.
            state: The state parameter for CSRF verification.

        Returns:
            SSOResult with tokens and character info.

        Raises:
            ValueError: If state doesn't match or token exchange fails.
        """
        if state != self._state:
            raise ValueError("State mismatch – possible CSRF attack")

        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            response = await client.post(
                ESI_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_id,
                    "code_verifier": self._code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            token_data = response.json()

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 1199)

        # Decode JWT to get character info
        character_id, character_name, scopes = self._decode_jwt(access_token)

        logger.info(
            "SSO login successful for %s (ID: %d)", character_name, character_id
        )

        return SSOResult(
            character_id=character_id,
            character_name=character_name,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            scopes=scopes,
        )

    async def refresh_access_token(self, refresh_token: str) -> SSOResult:
        """Refresh an expired access token.

        Args:
            refresh_token: The refresh token from a previous authentication.

        Returns:
            SSOResult with new tokens.
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                ESI_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            token_data = response.json()

        access_token = token_data["access_token"]
        new_refresh_token = token_data.get("refresh_token", refresh_token)
        expires_in = token_data.get("expires_in", 1199)

        character_id, character_name, scopes = self._decode_jwt(access_token)

        return SSOResult(
            character_id=character_id,
            character_name=character_name,
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=expires_in,
            scopes=scopes,
        )

    # EVE SSO may use either of these as issuer in the JWT.
    # See: https://developers.eveonline.com/docs/services/sso/
    ACCEPTED_ISSUERS = ("login.eveonline.com", "https://login.eveonline.com")

    def _decode_jwt(self, access_token: str) -> tuple[int, str, list[str]]:
        """Decode the JWT access token to extract character info.

        Args:
            access_token: The JWT access token from EVE SSO.

        Returns:
            Tuple of (character_id, character_name, scopes).
        """
        # Fetch JWKS for verification
        jwks_client = jwt.PyJWKClient(ESI_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(access_token)

        # EVE SSO tokens contain both "EVE Online" and the client_id in the
        # audience list.  PyJWT's ``audience`` check succeeds when *any* of
        # the expected values is present, so passing "EVE Online" is enough.
        # Pass the PyJWK object directly so PyJWT auto-detects the correct
        # algorithm from the key metadata.  CCP publishes both an RSA
        # (RS256) and an EC (ES256) key in JWKS and may sign with either.
        payload = jwt.decode(
            access_token,
            signing_key,
            algorithms=["RS256", "ES256"],
            audience="EVE Online",
            issuer=self.ACCEPTED_ISSUERS,
        )

        # Subject format: "CHARACTER:EVE:<character_id>"
        sub = payload.get("sub", "")
        character_id = int(sub.split(":")[-1])
        character_name = payload.get("name", "Unknown")
        scopes_str = payload.get("scp", [])
        scopes = scopes_str if isinstance(scopes_str, list) else [scopes_str]

        return character_id, character_name, scopes
