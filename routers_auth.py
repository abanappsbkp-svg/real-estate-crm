"""
Authentication Routes
Login, registration, token refresh, and user account management endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import os
import re

from pydantic import BaseModel, EmailStr, Field

from models import User, UserRole, Organization
from services_auth import AuthService, AuthenticationError
from middleware_auth import (
    get_current_user,
    get_optional_user,
    get_user_context,
    require_admin,
    UserContext,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    RefreshTokenRequest,
    ChangePasswordRequest,
    UserResponse,
    ErrorResponse,
)
from db import get_db

# Create router
router = APIRouter(prefix="/auth", tags=["Authentication"])

# ============================================================================
# First-time Setup: create an organization and its admin
# ============================================================================

class SetupRequest(BaseModel):
    """Create a new organization together with its first admin user"""
    organization_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None


@router.post(
    "/setup",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def setup_organization(
    data: SetupRequest,
    db: Session = Depends(get_db),
):
    """
    Create an organization and its first ADMIN user.

    Allowed only while the system has no organizations yet (first-time setup),
    unless the ALLOW_ORG_SIGNUP environment variable is set to "true".
    After this, log in with the same email/password and use /auth/register
    (with the returned organization_id) to add more users.
    """
    allow_signup = os.getenv("ALLOW_ORG_SIGNUP", "false").lower() == "true"
    if not allow_signup and db.query(Organization).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed. Ask your admin to add you as a user.",
        )

    base_slug = re.sub(r"[^a-z0-9]+", "-", data.organization_name.lower()).strip("-") or "org"
    slug = base_slug
    suffix = 1
    while db.query(Organization).filter(Organization.slug == slug).first():
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    org = Organization(name=data.organization_name, slug=slug)
    db.add(org)
    db.commit()
    db.refresh(org)

    try:
        user = AuthService(db).register_user(
            organization_id=str(org.id),
            email=data.email,
            password=data.password,
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
            role=UserRole.ADMIN,
        )
    except AuthenticationError as e:
        db.delete(org)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {
        "status": "success",
        "message": "Organization and admin user created. You can now log in.",
        "data": {
            "organization_id": str(org.id),
            "organization_slug": org.slug,
            "user": UserResponse.model_validate(user),
        },
    }

# ============================================================================
# Login Endpoint
# ============================================================================

@router.post(
    "/login",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        404: {"model": ErrorResponse, "description": "User not found"},
    },
)
async def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Authenticate user and return access/refresh tokens
    
    Request body:
    ```json
    {
        "email": "user@example.com",
        "password": "SecurePassword123!"
    }
    ```
    
    Returns:
    ```json
    {
        "status": "success",
        "data": {
            "user": {
                "id": "uuid",
                "email": "user@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "role": "agent",
                "is_active": true
            },
            "tokens": {
                "access_token": "eyJhbGci...",
                "refresh_token": "eyJhbGci...",
                "token_type": "bearer",
                "expires_in": 1800
            }
        }
    }
    ```
    """
    try:
        # Get client IP for audit logging
        client_ip = request.client.host if request.client else None
        
        # Authenticate user
        auth_service = AuthService(db)
        user, token_response = auth_service.login(
            email=credentials.email,
            password=credentials.password,
            ip_address=client_ip,
        )
        
        return {
            "status": "success",
            "message": f"Welcome {user.full_name}",
            "data": {
                "user": UserResponse.model_validate(user),
                "tokens": token_response.to_dict(),
            },
        }
    
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed",
        )

# ============================================================================
# Register Endpoint
# ============================================================================

@router.post(
    "/register",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Email already in use"},
    },
)
async def register(
    organization_id: str,
    user_data: RegisterRequest,
    db: Session = Depends(get_db),
):
    """
    Register a new user
    
    Note: In production, organization_id should come from context/config
    This is usually done by the organization admin during user management.
    
    Request body:
    ```json
    {
        "email": "newuser@example.com",
        "password": "SecurePassword123!",
        "confirm_password": "SecurePassword123!",
        "first_name": "John",
        "last_name": "Doe",
        "phone": "+1-555-0100"
    }
    ```
    
    Password requirements:
    - At least 8 characters
    - One uppercase letter
    - One lowercase letter
    - One digit
    - One special character
    """
    try:
        # Validate passwords match
        if user_data.password != user_data.confirm_password:
            raise AuthenticationError("Passwords do not match")
        
        # Register user
        auth_service = AuthService(db)
        user = auth_service.register_user(
            organization_id=organization_id,
            email=user_data.email,
            password=user_data.password,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            phone=user_data.phone,
            role=UserRole.VIEWER,  # Default role for new users
        )
        
        return {
            "status": "success",
            "message": "User registered successfully. Please log in.",
            "data": {
                "user": UserResponse.model_validate(user),
            },
        }
    
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed",
        )

# ============================================================================
# Get Current User
# ============================================================================

@router.get(
    "/me",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """
    Get current authenticated user's information
    
    Requires valid JWT token in Authorization header
    
    Returns:
    ```json
    {
        "status": "success",
        "data": {
            "user": {
                "id": "uuid",
                "email": "user@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "full_name": "John Doe",
                "role": "agent",
                "is_active": true,
                "organization_id": "uuid",
                "created_at": "2024-03-15T10:30:00Z"
            }
        }
    }
    ```
    """
    return {
        "status": "success",
        "data": {
            "user": UserResponse.model_validate(current_user),
            "organization_id": str(current_user.organization_id),
        },
    }

# ============================================================================
# Refresh Access Token
# ============================================================================

@router.post(
    "/refresh",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Invalid refresh token"},
    },
)
async def refresh_access_token(
    request_data: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Generate a new access token using a refresh token
    
    Refresh tokens expire after 7 days.
    Use this endpoint to get a new access token without requiring login.
    
    Request body:
    ```json
    {
        "refresh_token": "eyJhbGci..."
    }
    ```
    
    Returns:
    ```json
    {
        "status": "success",
        "data": {
            "tokens": {
                "access_token": "eyJhbGci...",
                "refresh_token": "eyJhbGci...",
                "token_type": "bearer",
                "expires_in": 1800
            }
        }
    }
    ```
    """
    try:
        auth_service = AuthService(db)
        token_response = auth_service.refresh_access_token(request_data.refresh_token)
        
        return {
            "status": "success",
            "message": "Access token refreshed",
            "data": {
                "tokens": token_response.to_dict(),
            },
        }
    
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token refresh failed",
        )

# ============================================================================
# Logout
# ============================================================================

@router.post(
    "/logout",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Logout current user
    
    Note: Actual logout happens on the frontend by deleting tokens.
    This endpoint is for audit logging purposes.
    
    Returns:
    ```json
    {
        "status": "success",
        "message": "Logged out successfully"
    }
    ```
    """
    auth_service = AuthService(db)
    auth_service.logout(
        user_id=str(current_user.id),
        organization_id=str(current_user.organization_id),
    )
    
    return {
        "status": "success",
        "message": "Logged out successfully",
    }

# ============================================================================
# Change Password
# ============================================================================

@router.post(
    "/change-password",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid password"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
    },
)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change user's password
    
    Requires current password and new password.
    Password must meet security requirements.
    
    Request body:
    ```json
    {
        "old_password": "CurrentPassword123!",
        "new_password": "NewPassword456!",
        "confirm_password": "NewPassword456!"
    }
    ```
    """
    try:
        # Validate new passwords match
        if password_data.new_password != password_data.confirm_password:
            raise AuthenticationError("New passwords do not match")
        
        auth_service = AuthService(db)
        user = auth_service.change_password(
            user_id=str(current_user.id),
            old_password=password_data.old_password,
            new_password=password_data.new_password,
        )
        
        return {
            "status": "success",
            "message": "Password changed successfully",
            "data": {
                "user": UserResponse.model_validate(user),
            },
        }
    
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password",
        )

# ============================================================================
# Update Profile
# ============================================================================

@router.patch(
    "/me/profile",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def update_profile(
    profile_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update current user's profile
    
    Can update:
    - first_name
    - last_name
    - phone
    - avatar_url
    - preferred_language
    
    Request body (all fields optional):
    ```json
    {
        "first_name": "John",
        "last_name": "Doe",
        "phone": "+1-555-0100",
        "avatar_url": "https://...",
        "preferred_language": "en"
    }
    ```
    """
    try:
        auth_service = AuthService(db)
        user = auth_service.update_user_profile(
            user_id=str(current_user.id),
            **profile_data,
        )
        
        return {
            "status": "success",
            "message": "Profile updated successfully",
            "data": {
                "user": UserResponse.model_validate(user),
            },
        }
    
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        )

# ============================================================================
# Password Reset (Request)
# ============================================================================

@router.post(
    "/forgot-password",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def request_password_reset(
    email_data: dict,  # {"email": "user@example.com"}
    db: Session = Depends(get_db),
):
    """
    Request a password reset email
    
    Sends a password reset link to the user's email.
    The link is valid for 24 hours.
    
    Request body:
    ```json
    {
        "email": "user@example.com"
    }
    ```
    
    Note: This endpoint returns success regardless of whether
    the email exists (security best practice).
    """
    try:
        auth_service = AuthService(db)
        auth_service.request_password_reset(email_data.get("email", ""))
        
        return {
            "status": "success",
            "message": "If an account with that email exists, "
                      "a password reset link has been sent.",
        }
    
    except Exception as e:
        # Don't expose error details
        return {
            "status": "success",
            "message": "If an account with that email exists, "
                      "a password reset link has been sent.",
        }

# ============================================================================
# Health Check
# ============================================================================

@router.get(
    "/health",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def health_check():
    """
    Check authentication service health
    
    Returns:
    ```json
    {
        "status": "healthy",
        "timestamp": "2024-03-15T10:30:00Z"
    }
    ```
    """
    return {
        "status": "healthy",
        "service": "authentication",
        "timestamp": datetime.utcnow().isoformat(),
    }

# ============================================================================
# Admin Only: List Users
# ============================================================================

@router.get(
    "/admin/users",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin())],
)
async def list_users(
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """
    List all users in the organization (ADMIN ONLY)
    
    Requires admin role
    """
    from models import User as UserModel
    
    users = db.query(UserModel).filter(
        UserModel.organization_id == current_user.organization_id,
    ).all()
    
    return {
        "status": "success",
        "data": {
            "users": [UserResponse.model_validate(u) for u in users],
            "total": len(users),
        },
    }

# ============================================================================
# Admin Only: Change User Role
# ============================================================================

@router.patch(
    "/admin/users/{user_id}/role",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin())],
)
async def change_user_role(
    user_id: str,
    role_data: dict,  # {"role": "agent"}
    current_user: User = Depends(require_admin()),
    db: Session = Depends(get_db),
):
    """
    Change a user's role (ADMIN ONLY)
    
    Valid roles:
    - admin
    - agent
    - viewer
    
    Request body:
    ```json
    {
        "role": "agent"
    }
    ```
    """
    from models import User as UserModel
    
    try:
        new_role = role_data.get("role")
        if new_role not in ["admin", "agent", "viewer"]:
            raise ValueError("Invalid role")
        
        user = db.query(UserModel).filter(
            UserModel.id == user_id,
            UserModel.organization_id == current_user.organization_id,
        ).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        
        user.role = new_role
        db.commit()
        db.refresh(user)
        
        return {
            "status": "success",
            "message": f"User role changed to {new_role}",
            "data": {
                "user": UserResponse.model_validate(user),
            },
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
