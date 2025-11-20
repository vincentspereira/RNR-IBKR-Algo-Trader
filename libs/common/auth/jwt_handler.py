"""JWT token handling and authentication utilities."""
import jwt
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TokenPayload(BaseModel):
    """JWT token payload structure."""
    
    sub: str = Field(..., description="Subject (user_id)")
    exp: datetime = Field(..., description="Expiration time")
    iat: datetime = Field(..., description="Issued at time")
    roles: List[str] = Field(default_factory=list, description="User roles")
    permissions: List[str] = Field(default_factory=list, description="User permissions")
    
    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: int(v.timestamp())
        }


class JWTHandler:
    """JWT token generation and validation."""
    
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        """
        Initialize JWT handler.
        
        Args:
            secret_key: Secret key for signing tokens
            algorithm: JWT algorithm (default: HS256)
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
    
    def create_access_token(
        self,
        user_id: str,
        roles: List[str],
        permissions: List[str],
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create JWT access token.
        
        Args:
            user_id: User identifier
            roles: List of user roles
            permissions: List of user permissions
            expires_delta: Token expiration time (default: 15 minutes)
            
        Returns:
            Encoded JWT token
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=15)
        
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "exp": now + expires_delta,
            "iat": now,
            "roles": roles,
            "permissions": permissions,
        }
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def create_refresh_token(
        self,
        user_id: str,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create JWT refresh token.
        
        Args:
            user_id: User identifier
            expires_delta: Token expiration time (default: 7 days)
            
        Returns:
            Encoded JWT refresh token
        """
        if expires_delta is None:
            expires_delta = timedelta(days=7)
        
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "exp": now + expires_delta,
            "iat": now,
            "type": "refresh",
        }
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str) -> Optional[TokenPayload]:
        """
        Verify and decode JWT token.
        
        Args:
            token: JWT token to verify
            
        Returns:
            Decoded token payload or None if invalid
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            
            # Convert timestamp to datetime
            payload['exp'] = datetime.fromtimestamp(payload['exp'])
            payload['iat'] = datetime.fromtimestamp(payload['iat'])
            
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def decode_token_without_verification(self, token: str) -> Optional[Dict]:
        """
        Decode token without verification (for debugging).
        
        Args:
            token: JWT token to decode
            
        Returns:
            Decoded payload or None
        """
        try:
            return jwt.decode(
                token,
                options={"verify_signature": False}
            )
        except Exception:
            return None


class PermissionChecker:
    """Check user permissions."""
    
    @staticmethod
    def has_permission(user_permissions: List[str], required_permission: str) -> bool:
        """
        Check if user has required permission.
        
        Args:
            user_permissions: List of user permissions
            required_permission: Required permission
            
        Returns:
            True if user has permission
        """
        # Wildcard permission
        if "*" in user_permissions:
            return True
        
        # Exact match
        if required_permission in user_permissions:
            return True
        
        # Pattern matching (e.g., "trading.*" matches "trading.create_order")
        for perm in user_permissions:
            if perm.endswith(".*"):
                prefix = perm[:-2]
                if required_permission.startswith(prefix + "."):
                    return True
        
        return False
    
    @staticmethod
    def has_role(user_roles: List[str], required_role: str) -> bool:
        """
        Check if user has required role.
        
        Args:
            user_roles: List of user roles
            required_role: Required role
            
        Returns:
            True if user has role
        """
        return required_role in user_roles
