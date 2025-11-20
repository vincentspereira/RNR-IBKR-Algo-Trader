"""Keycloak integration for authentication and authorization."""
from typing import Dict, List, Optional
import httpx


class KeycloakClient:
    """Keycloak client for authentication and user management."""
    
    def __init__(
        self,
        server_url: str,
        realm: str,
        client_id: str,
        client_secret: Optional[str] = None
    ):
        """
        Initialize Keycloak client.
        
        Args:
            server_url: Keycloak server URL
            realm: Keycloak realm name
            client_id: Client ID
            client_secret: Client secret (optional)
        """
        self.server_url = server_url.rstrip('/')
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = f"{self.server_url}/realms/{self.realm}"
    
    async def authenticate(self, username: str, password: str) -> Optional[Dict]:
        """
        Authenticate user with username and password.
        
        Args:
            username: Username
            password: Password
            
        Returns:
            Token response or None if authentication failed
        """
        url = f"{self.base_url}/protocol/openid-connect/token"
        data = {
            "grant_type": "password",
            "client_id": self.client_id,
            "username": username,
            "password": password,
        }
        
        if self.client_secret:
            data["client_secret"] = self.client_secret
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, data=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                return None
    
    async def refresh_token(self, refresh_token: str) -> Optional[Dict]:
        """
        Refresh access token using refresh token.
        
        Args:
            refresh_token: Refresh token
            
        Returns:
            New token response or None if refresh failed
        """
        url = f"{self.base_url}/protocol/openid-connect/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        
        if self.client_secret:
            data["client_secret"] = self.client_secret
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, data=data)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                return None
    
    async def get_user_info(self, access_token: str) -> Optional[Dict]:
        """
        Get user information from access token.
        
        Args:
            access_token: Access token
            
        Returns:
            User information or None
        """
        url = f"{self.base_url}/protocol/openid-connect/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                return None
    
    async def logout(self, refresh_token: str) -> bool:
        """
        Logout user by invalidating refresh token.
        
        Args:
            refresh_token: Refresh token
            
        Returns:
            True if logout successful
        """
        url = f"{self.base_url}/protocol/openid-connect/logout"
        data = {
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        
        if self.client_secret:
            data["client_secret"] = self.client_secret
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, data=data)
                response.raise_for_status()
                return True
            except httpx.HTTPError:
                return False
