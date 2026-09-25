"""
Authentication Utilities
Handles JWT tokens, password hashing, and credential validation
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
import uuid

from config import settings

# ============================================================================
# Password Hashing
# ============================================================================

# Use Argon2 for password hashing (most secure)
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
)

def hash_password(password: str) -> str:
    """Hash a password using Argon2"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)

# ============================================================================
# JWT Token Management
# ============================================================================

class TokenData:
    """JWT token payload data"""
    
    def __init__(
        self,
        user_id: str,
        organization_id: str,
        email: str,
        role: str,
        exp: Optional[datetime] = None,
    ):
        self.user_id = user_id
        self.organization_id = organization_id
        self.email = email
        self.role = role
        self.exp = exp or (datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JWT encoding"""
        return {
            "sub": self.user_id,  # subject (standard JWT claim)
            "org_id": self.organization_id,
            "email": self.email,
            "role": self.role,
            "exp": self.exp,
            "iat": datetime.utcnow(),  # issued at
            "type": "access",
        }

class RefreshTokenData:
    """Refresh token payload"""
    
    def __init__(
        self,
        user_id: str,
        organization_id: str,
        exp: Optional[datetime] = None,
    ):
        self.user_id = user_id
        self.organization_id = organization_id
        self.exp = exp or (datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JWT encoding"""
        return {
            "sub": self.user_id,
            "org_id": self.organization_id,
            "exp": self.exp,
            "iat": datetime.utcnow(),
            "type": "refresh",
        }

def create_access_token(token_data: TokenData) -> str:
    """
    Create a JWT access token
    
    Args:
        token_data: TokenData object with user information
    
    Returns:
        Encoded JWT token string
    """
    payload = token_data.to_dict()
    
    encoded_jwt = jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return encoded_jwt

def create_refresh_token(token_data: RefreshTokenData) -> str:
    """
    Create a JWT refresh token
    
    Args:
        token_data: RefreshTokenData object
    
    Returns:
        Encoded JWT token string
    """
    payload = token_data.to_dict()
    
    encoded_jwt = jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return encoded_jwt

def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode a JWT token
    
    Args:
        token: JWT token string
    
    Returns:
        Decoded token payload
    
    Raises:
        JWTError: If token is invalid or expired
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        return payload
    except JWTError as e:
        raise JWTError(f"Invalid token: {str(e)}")

def extract_token_from_header(authorization_header: str) -> Optional[str]:
    """
    Extract JWT token from Authorization header
    
    Expected format: "Bearer <token>"
    
    Args:
        authorization_header: Authorization header value
    
    Returns:
        Token string or None if invalid format
    """
    if not authorization_header:
        return None
    
    parts = authorization_header.split()
    
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    
    return parts[1]

# ============================================================================
# Token Response Models
# ============================================================================

class TokenResponse:
    """Response containing access and refresh tokens"""
    
    def __init__(self, access_token: str, refresh_token: str):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = "bearer"
        self.expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # in seconds
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
        }

# ============================================================================
# Email Validation
# ============================================================================

import re

def is_valid_email(email: str) -> bool:
    """
    Validate email format
    
    Args:
        email: Email address to validate
    
    Returns:
        True if valid email format
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# ============================================================================
# Password Validation
# ============================================================================

def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets security requirements
    
    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    
    Args:
        password: Password to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        return False, "Password must contain at least one special character"
    
    return True, ""

# ============================================================================
# Session Management
# ============================================================================

class SessionData:
    """In-memory session storage (for development/testing)"""
    
    _sessions: Dict[str, Dict[str, Any]] = {}
    
    @staticmethod
    def create_session(user_id: str, organization_id: str, role: str) -> str:
        """Create a new session"""
        session_id = str(uuid.uuid4())
        SessionData._sessions[session_id] = {
            "user_id": user_id,
            "organization_id": organization_id,
            "role": role,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(hours=24),
        }
        return session_id
    
    @staticmethod
    def get_session(session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data"""
        session = SessionData._sessions.get(session_id)
        
        if not session:
            return None
        
        # Check if expired
        if datetime.utcnow() > session["expires_at"]:
            del SessionData._sessions[session_id]
            return None
        
        return session
    
    @staticmethod
    def delete_session(session_id: str):
        """Delete a session"""
        if session_id in SessionData._sessions:
            del SessionData._sessions[session_id]
    
    @staticmethod
    def clear_all_sessions():
        """Clear all sessions (for testing)"""
        SessionData._sessions.clear()

# ============================================================================
# Constants
# ============================================================================

# Error messages
ERROR_INVALID_CREDENTIALS = "Invalid email or password"
ERROR_INVALID_TOKEN = "Invalid or expired token"
ERROR_INSUFFICIENT_PERMISSIONS = "Insufficient permissions"
ERROR_USER_NOT_FOUND = "User not found"
ERROR_USER_INACTIVE = "User account is inactive"
ERROR_EMAIL_TAKEN = "Email already in use"
ERROR_WEAK_PASSWORD = "Password does not meet security requirements"
ERROR_INVALID_EMAIL = "Invalid email format"
