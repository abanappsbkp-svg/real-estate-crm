"""
Authentication Service
Business logic for user authentication and authorization
"""

from typing import Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import uuid
from models import as_uuid

from models import User, Organization, UserRole, AuditLog
from utils_auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
    TokenData,
    RefreshTokenData,
    TokenResponse,
    is_valid_email,
    validate_password_strength,
    ERROR_INVALID_CREDENTIALS,
    ERROR_INVALID_TOKEN,
    ERROR_USER_NOT_FOUND,
    ERROR_USER_INACTIVE,
    ERROR_EMAIL_TAKEN,
    ERROR_INVALID_EMAIL,
    ERROR_WEAK_PASSWORD,
)

class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass

class AuthorizationError(Exception):
    """Raised when user lacks permissions"""
    pass

class AuthService:
    """Service for authentication and authorization"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ========================================================================
    # User Registration
    # ========================================================================
    
    def register_user(
        self,
        organization_id: str,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        phone: Optional[str] = None,
        role: UserRole = UserRole.VIEWER,
    ) -> User:
        """
        Register a new user
        
        Args:
            organization_id: Organization UUID
            email: User's email address
            password: User's password (will be hashed)
            first_name: First name
            last_name: Last name
            phone: Optional phone number
            role: User role (default: viewer)
        
        Returns:
            Created User object
        
        Raises:
            AuthenticationError: If validation fails
        """
        # Validate email format
        if not is_valid_email(email):
            raise AuthenticationError(ERROR_INVALID_EMAIL)
        
        # Validate password strength
        is_strong, error_msg = validate_password_strength(password)
        if not is_strong:
            raise AuthenticationError(error_msg)
        
        # Check if organization exists
        org = self.db.query(Organization).filter(
            Organization.id == as_uuid(organization_id)
        ).first()
        
        if not org:
            raise AuthenticationError("Organization not found")
        
        # Check if email already exists in organization
        existing_user = self.db.query(User).filter(
            and_(
                User.organization_id == as_uuid(organization_id),
                User.email == email.lower(),
            )
        ).first()
        
        if existing_user:
            raise AuthenticationError(ERROR_EMAIL_TAKEN)
        
        # Create new user
        user = User(
            organization_id=as_uuid(organization_id),
            email=email.lower(),
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            role=role.value,
            is_active=True,
        )
        
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        
        # Log registration
        self._log_audit(
            organization_id=organization_id,
            user_id=str(user.id),
            action="user_registered",
            entity_type="user",
            entity_id=str(user.id),
            new_values={"email": email, "role": role.value},
        )
        
        return user
    
    # ========================================================================
    # User Login
    # ========================================================================
    
    def login(
        self,
        email: str,
        password: str,
        ip_address: Optional[str] = None,
    ) -> Tuple[User, TokenResponse]:
        """
        Authenticate user and generate tokens
        
        Args:
            email: User's email address
            password: User's password (plain text)
            ip_address: Optional IP address for audit logging
        
        Returns:
            Tuple of (User object, TokenResponse with access/refresh tokens)
        
        Raises:
            AuthenticationError: If credentials are invalid
        """
        # Find user by email
        user = self.db.query(User).filter(
            User.email == email.lower()
        ).first()
        
        if not user:
            # Log failed attempt
            self._log_audit(
                organization_id=None,
                user_id=None,
                action="login_failed",
                status="failed",
                error_message=f"User not found: {email}",
                ip_address=ip_address,
            )
            raise AuthenticationError(ERROR_INVALID_CREDENTIALS)
        
        # Check if user is active
        if not user.is_active:
            self._log_audit(
                organization_id=str(user.organization_id),
                user_id=str(user.id),
                action="login_failed",
                status="failed",
                error_message="User account is inactive",
                ip_address=ip_address,
            )
            raise AuthenticationError(ERROR_USER_INACTIVE)
        
        # Verify password
        if not verify_password(password, user.password_hash):
            self._log_audit(
                organization_id=str(user.organization_id),
                user_id=str(user.id),
                action="login_failed",
                status="failed",
                error_message="Invalid password",
                ip_address=ip_address,
            )
            raise AuthenticationError(ERROR_INVALID_CREDENTIALS)
        
        # Update last login
        user.last_login = datetime.utcnow()
        self.db.commit()
        
        # Generate tokens
        access_token_data = TokenData(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
            email=user.email,
            role=user.role,
        )
        access_token = create_access_token(access_token_data)
        
        refresh_token_data = RefreshTokenData(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
        )
        refresh_token = create_refresh_token(refresh_token_data)
        
        token_response = TokenResponse(access_token, refresh_token)
        
        # Log successful login
        self._log_audit(
            organization_id=str(user.organization_id),
            user_id=str(user.id),
            action="user_login",
            ip_address=ip_address,
        )
        
        return user, token_response
    
    # ========================================================================
    # Token Refresh
    # ========================================================================
    
    def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        """
        Generate a new access token using a refresh token
        
        Args:
            refresh_token: JWT refresh token
        
        Returns:
            TokenResponse with new access token
        
        Raises:
            AuthenticationError: If refresh token is invalid
        """
        try:
            # Verify refresh token
            payload = verify_token(refresh_token)
            
            # Check token type
            if payload.get("type") != "refresh":
                raise AuthenticationError(ERROR_INVALID_TOKEN)
            
            user_id = payload.get("sub")
            organization_id = payload.get("org_id")
            
            # Get user
            user = self.db.query(User).filter(
                User.id == as_uuid(user_id)
            ).first()
            
            if not user or not user.is_active:
                raise AuthenticationError(ERROR_USER_NOT_FOUND)
            
            # Generate new access token
            access_token_data = TokenData(
                user_id=str(user.id),
                organization_id=str(user.organization_id),
                email=user.email,
                role=user.role,
            )
            access_token = create_access_token(access_token_data)
            
            # Generate new refresh token
            refresh_token_data = RefreshTokenData(
                user_id=str(user.id),
                organization_id=str(user.organization_id),
            )
            new_refresh_token = create_refresh_token(refresh_token_data)
            
            return TokenResponse(access_token, new_refresh_token)
        
        except Exception as e:
            raise AuthenticationError(ERROR_INVALID_TOKEN)
    
    # ========================================================================
    # Token Verification
    # ========================================================================
    
    def verify_access_token(self, token: str) -> User:
        """
        Verify an access token and return the associated user
        
        Args:
            token: JWT access token
        
        Returns:
            User object
        
        Raises:
            AuthenticationError: If token is invalid or user not found
        """
        try:
            payload = verify_token(token)
            
            # Check token type
            if payload.get("type") != "access":
                raise AuthenticationError(ERROR_INVALID_TOKEN)
            
            user_id = payload.get("sub")
            
            # Get user
            user = self.db.query(User).filter(
                User.id == as_uuid(user_id)
            ).first()
            
            if not user or not user.is_active:
                raise AuthenticationError(ERROR_USER_NOT_FOUND)
            
            return user
        
        except Exception as e:
            raise AuthenticationError(ERROR_INVALID_TOKEN)
    
    # ========================================================================
    # Logout
    # ========================================================================
    
    def logout(self, user_id: str, organization_id: str):
        """
        Log user logout (audit only - actual logout happens on frontend)
        
        Args:
            user_id: User UUID
            organization_id: Organization UUID
        """
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="user_logout",
        )
    
    # ========================================================================
    # Password Management
    # ========================================================================
    
    def change_password(
        self,
        user_id: str,
        old_password: str,
        new_password: str,
    ) -> User:
        """
        Change user's password
        
        Args:
            user_id: User UUID
            old_password: Current password (plain text)
            new_password: New password (plain text)
        
        Returns:
            Updated User object
        
        Raises:
            AuthenticationError: If old password is invalid
        """
        # Get user
        user = self.db.query(User).filter(
            User.id == as_uuid(user_id)
        ).first()
        
        if not user:
            raise AuthenticationError(ERROR_USER_NOT_FOUND)
        
        # Verify old password
        if not verify_password(old_password, user.password_hash):
            raise AuthenticationError("Incorrect current password")
        
        # Validate new password strength
        is_strong, error_msg = validate_password_strength(new_password)
        if not is_strong:
            raise AuthenticationError(error_msg)
        
        # Update password
        user.password_hash = hash_password(new_password)
        self.db.commit()
        self.db.refresh(user)
        
        # Log change
        self._log_audit(
            organization_id=str(user.organization_id),
            user_id=str(user.id),
            action="password_changed",
        )
        
        return user
    
    def request_password_reset(self, email: str) -> bool:
        """
        Request a password reset (sends email)
        
        Args:
            email: User's email address
        
        Returns:
            True if reset email was sent
        
        Note:
            In production, this would:
            1. Create a password reset token
            2. Store it in database with expiration
            3. Send email with reset link
        """
        user = self.db.query(User).filter(
            User.email == email.lower()
        ).first()
        
        if not user:
            # Don't reveal if email exists (security best practice)
            return False
        
        # TODO: Implement password reset email
        # 1. Generate reset token
        # 2. Save to database with expiration
        # 3. Send email
        
        self._log_audit(
            organization_id=str(user.organization_id),
            user_id=str(user.id),
            action="password_reset_requested",
        )
        
        return True
    
    # ========================================================================
    # User Management
    # ========================================================================
    
    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        return self.db.query(User).filter(
            User.id == as_uuid(user_id)
        ).first()
    
    def update_user_profile(
        self,
        user_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None,
        avatar_url: Optional[str] = None,
        preferred_language: Optional[str] = None,
    ) -> User:
        """Update user profile information"""
        user = self.get_user(user_id)
        
        if not user:
            raise AuthenticationError(ERROR_USER_NOT_FOUND)
        
        # Update fields if provided
        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        if phone:
            user.phone = phone
        if avatar_url:
            user.avatar_url = avatar_url
        if preferred_language:
            user.preferred_language = preferred_language
        
        user.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(user)
        
        return user
    
    # ========================================================================
    # Authorization
    # ========================================================================
    
    def check_permission(
        self,
        user: User,
        required_role: UserRole,
    ) -> bool:
        """
        Check if user has required role
        
        Args:
            user: User object
            required_role: Required UserRole
        
        Returns:
            True if user has permission
        """
        # Admin can do everything
        if user.role == UserRole.ADMIN.value:
            return True
        
        # Check specific role
        if user.role == required_role.value:
            return True
        
        return False
    
    def require_role(self, user: User, *roles: UserRole):
        """
        Require user to have one of specified roles
        
        Args:
            user: User object
            *roles: Required roles
        
        Raises:
            AuthorizationError: If user doesn't have required role
        """
        if user.role == UserRole.ADMIN.value:
            return  # Admin has all permissions
        
        if user.role not in [r.value for r in roles]:
            raise AuthorizationError(
                f"User role '{user.role}' is not authorized for this action"
            )
    
    # ========================================================================
    # Private Methods
    # ========================================================================
    
    def _log_audit(
        self,
        organization_id: Optional[str],
        user_id: Optional[str],
        action: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        ip_address: Optional[str] = None,
    ):
        """Log audit trail entry"""
        if not organization_id:
            return  # Don't log if no org (e.g., during login attempt)
        
        audit_log = AuditLog(
            organization_id=as_uuid(organization_id),
            user_id=as_uuid(user_id) if user_id else None,
            action=action,
            entity_type=entity_type,
            entity_id=as_uuid(entity_id) if entity_id else None,
            old_values=old_values,
            new_values=new_values,
            status=status,
            error_message=error_message,
            ip_address=ip_address,
        )
        self.db.add(audit_log)
        self.db.commit()
