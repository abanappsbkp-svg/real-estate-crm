"""
Authentication Middleware
Handles JWT verification and user context injection
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from typing import Optional, Callable

from models import User, UserRole
from services_auth import AuthService
from utils_auth import extract_token_from_header, ERROR_INVALID_TOKEN
from main import get_db

# ============================================================================
# HTTP Bearer Security
# ============================================================================

security = HTTPBearer(
    scheme_name="Bearer",
    description="JWT Bearer token",
    auto_error=False,  # Don't auto-throw, we'll handle it
)

# ============================================================================
# Get Current User from Token
# ============================================================================

async def get_current_user(
    credentials: Optional[HTTPAuthCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Extract and verify JWT token, return authenticated user
    
    This dependency should be used in protected routes:
    
    @router.get("/protected")
    async def protected_route(current_user: User = Depends(get_current_user)):
        return {"message": f"Hello {current_user.full_name}"}
    
    Args:
        credentials: HTTP Bearer credentials
        db: Database session
    
    Returns:
        User object from verified token
    
    Raises:
        HTTPException: If token is missing or invalid
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    try:
        auth_service = AuthService(db)
        user = auth_service.verify_access_token(token)
        return user
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

# ============================================================================
# Optional User (for public routes that allow auth)
# ============================================================================

async def get_optional_user(
    credentials: Optional[HTTPAuthCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Extract JWT token if present, return user or None if invalid/missing
    
    Use for routes that work both authenticated and unauthenticated:
    
    @router.get("/public")
    async def public_route(current_user: Optional[User] = Depends(get_optional_user)):
        if current_user:
            return {"message": f"Hello {current_user.full_name}"}
        else:
            return {"message": "Hello anonymous"}
    
    Args:
        credentials: HTTP Bearer credentials
        db: Database session
    
    Returns:
        User object if authenticated, None otherwise
    """
    if not credentials:
        return None
    
    try:
        auth_service = AuthService(db)
        user = auth_service.verify_access_token(credentials.credentials)
        return user
    except:
        return None

# ============================================================================
# Role-Based Access Control
# ============================================================================

def require_role(*required_roles: UserRole) -> Callable:
    """
    Dependency factory that requires one of specified roles
    
    Usage:
    
    @router.delete("/properties/{id}")
    async def delete_property(
        property_id: str,
        current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.AGENT)),
    ):
        # Only admins and agents can delete
        pass
    
    Args:
        *required_roles: One or more UserRole values that are allowed
    
    Returns:
        Dependency function that validates user role
    """
    async def check_role(
        current_user: User = Depends(get_current_user),
    ) -> User:
        # Admin has all permissions
        if current_user.role == UserRole.ADMIN.value:
            return current_user
        
        # Check if user has one of required roles
        if current_user.role not in [r.value for r in required_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User role '{current_user.role}' does not have permission. "
                       f"Required roles: {', '.join(r.value for r in required_roles)}",
            )
        
        return current_user
    
    return check_role

def require_admin() -> Callable:
    """
    Dependency that requires admin role
    
    Usage:
    
    @router.delete("/users/{user_id}")
    async def delete_user(
        user_id: str,
        current_user: User = Depends(require_admin()),
    ):
        # Only admins can delete users
        pass
    """
    return require_role(UserRole.ADMIN)

def require_agent_or_admin() -> Callable:
    """Dependency that requires agent or admin role"""
    return require_role(UserRole.AGENT, UserRole.ADMIN)

# ============================================================================
# Organization-Based Access Control
# ============================================================================

async def verify_org_access(
    organization_id: str,
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Verify user belongs to the requested organization
    
    Usage:
    
    @router.get("/organizations/{org_id}/users")
    async def get_org_users(
        org_id: str,
        current_user: User = Depends(verify_org_access(org_id)),
    ):
        # Only users in the organization can view its users
        pass
    
    Args:
        organization_id: Organization UUID
        current_user: Authenticated user
    
    Returns:
        User if authorized, raises exception otherwise
    
    Raises:
        HTTPException: If user doesn't belong to organization
    """
    if str(current_user.organization_id) != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied - user does not belong to this organization",
        )
    
    return current_user

# ============================================================================
# User Context Dependency
# ============================================================================

class UserContext:
    """Encapsulates current user context"""
    
    def __init__(self, user: User):
        self.user_id = str(user.id)
        self.organization_id = str(user.organization_id)
        self.role = user.role
        self.email = user.email
        self.preferred_language = user.preferred_language
    
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value
    
    def is_agent(self) -> bool:
        return self.role == UserRole.AGENT.value
    
    def is_viewer(self) -> bool:
        return self.role == UserRole.VIEWER.value
    
    def has_role(self, role: UserRole) -> bool:
        return self.role == role.value or self.is_admin()

async def get_user_context(
    current_user: User = Depends(get_current_user),
) -> UserContext:
    """
    Get user context object
    
    Usage:
    
    @router.get("/me/context")
    async def get_context(context: UserContext = Depends(get_user_context)):
        return {
            "user_id": context.user_id,
            "organization_id": context.organization_id,
            "role": context.role,
            "is_admin": context.is_admin(),
        }
    """
    return UserContext(current_user)

# ============================================================================
# Request/Response Models for Auth
# ============================================================================

from pydantic import BaseModel, EmailStr

class LoginRequest(BaseModel):
    """Login request payload"""
    email: EmailStr
    password: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "agent@example.com",
                "password": "SecurePassword123!",
            }
        }

class RegisterRequest(BaseModel):
    """User registration request"""
    email: EmailStr
    password: str
    confirm_password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "newagent@example.com",
                "password": "SecurePassword123!",
                "confirm_password": "SecurePassword123!",
                "first_name": "John",
                "last_name": "Doe",
                "phone": "+1-555-0100",
            }
        }

class TokenResponse(BaseModel):
    """Token response payload"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    
    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 1800,
            }
        }

class RefreshTokenRequest(BaseModel):
    """Refresh token request"""
    refresh_token: str

class ChangePasswordRequest(BaseModel):
    """Change password request"""
    old_password: str
    new_password: str
    confirm_password: str

class UserResponse(BaseModel):
    """User response (for API responses)"""
    id: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    full_name: Optional[str]
    phone: Optional[str]
    role: str
    avatar_url: Optional[str]
    preferred_language: str
    is_active: bool
    last_login: Optional[str]
    created_at: str
    
    class Config:
        from_attributes = True

# ============================================================================
# Error Responses
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: str
    status_code: int
    timestamp: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "AUTHENTICATION_ERROR",
                "detail": "Invalid email or password",
                "status_code": 401,
                "timestamp": "2024-03-15T10:30:00Z",
            }
        }
