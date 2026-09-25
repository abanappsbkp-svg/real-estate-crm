"""
Clients API Routes
Endpoints for client management, interactions, and property matching
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

from middleware_auth import (
    get_current_user, UserContext, require_role
)
from services_clients import ClientService
from models import User, UserRole
from db import get_db

# ============================================================================
# Pydantic Models
# ============================================================================

class PreferencesRequest(BaseModel):
    budget_min: Optional[float] = Field(None, gt=0)
    budget_max: Optional[float] = Field(None, gt=0)
    property_types: Optional[List[str]] = None
    bedrooms: Optional[int] = Field(None, ge=0)
    bathrooms: Optional[float] = Field(None, ge=0)
    location_preferences: Optional[Dict[str, Any]] = None

class CreateClientRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = None
    client_type: str = Field(default="buyer", regex="^(buyer|seller|both)$")
    status: str = Field(default="active", regex="^(active|inactive|archived)$")
    preferences: Optional[PreferencesRequest] = None
    notes: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None

class UpdateClientRequest(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    client_type: Optional[str] = Field(None, regex="^(buyer|seller|both)$")
    status: Optional[str] = Field(None, regex="^(active|inactive|archived)$")
    notes: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None

class InteractionRequest(BaseModel):
    interaction_type: str = Field(..., regex="^(call|email|meeting|showing|offer)$")
    description: Optional[str] = None
    property_id: Optional[str] = None
    notes: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, ge=1)
    follow_up_date: Optional[datetime] = None

class ClientInteractionResponse(BaseModel):
    id: str
    client_id: str
    user_id: str
    type: str
    description: Optional[str]
    property_id: Optional[str]
    notes: Optional[str]
    duration_minutes: Optional[int]
    follow_up_date: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True

class ClientResponse(BaseModel):
    id: str
    organization_id: str
    email: str
    first_name: str
    last_name: str
    phone: Optional[str]
    type: str
    status: str
    budget_min: Optional[float]
    budget_max: Optional[float]
    property_type_preferences: List[str]
    bedroom_preferences: Optional[int]
    location_preferences: Dict[str, Any]
    notes: Optional[str]
    interaction_count: Optional[int]
    last_interaction_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    created_by_id: str
    
    class Config:
        from_attributes = True

class ClientListResponse(BaseModel):
    clients: List[ClientResponse]
    total: int
    skip: int
    limit: int

class PropertyMatchResponse(BaseModel):
    id: str
    client_id: str
    property_id: str
    match_score: float
    match_reason: List[str]
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class ClientStatsResponse(BaseModel):
    total_clients: int
    buyers: int
    sellers: int
    active: int
    active_recently: int
    percentage_buyers: float
    percentage_sellers: float
    percentage_active: float

# ============================================================================
# Router Setup
# ============================================================================

router = APIRouter(
    prefix="/clients",
    tags=["Clients"],
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        404: {"description": "Not found"},
    }
)

# ============================================================================
# CREATE Client
# ============================================================================

@router.post(
    "",
    response_model=ClientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new client",
    description="Create a new client profile (Agents and Admins only)",
)
async def create_client(
    request: CreateClientRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ClientResponse:
    """
    Create a new client profile
    
    - **email**: Client's email (must be unique within org)
    - **first_name**: First name (required)
    - **last_name**: Last name (required)
    - **phone**: Phone number (optional)
    - **client_type**: buyer, seller, or both (default: buyer)
    - **status**: active, inactive, or archived (default: active)
    - **preferences**: Budget, property type, location, bedroom preferences
    - **notes**: Internal notes about client
    - **custom_fields**: Any custom data
    
    Only Agents and Admins can create clients.
    """
    try:
        service = ClientService(db)
        
        # Extract preferences if provided
        budget_min = request.preferences.budget_min if request.preferences else None
        budget_max = request.preferences.budget_max if request.preferences else None
        property_types = request.preferences.property_types if request.preferences else None
        bedrooms = request.preferences.bedrooms if request.preferences else None
        location_prefs = request.preferences.location_preferences if request.preferences else None
        
        client = service.create_client(
            organization_id=current_user.organization_id,
            created_by_id=current_user.user_id,
            email=request.email,
            first_name=request.first_name,
            last_name=request.last_name,
            phone=request.phone,
            client_type=request.client_type,
            status=request.status,
            budget_min=budget_min,
            budget_max=budget_max,
            property_type_preferences=property_types,
            bedroom_preferences=bedrooms,
            location_preferences=location_prefs,
            notes=request.notes,
            custom_fields=request.custom_fields,
        )
        
        return ClientResponse.model_validate(client)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create client")

# ============================================================================
# LIST Clients
# ============================================================================

@router.get(
    "",
    response_model=ClientListResponse,
    summary="List clients",
    description="List all clients in organization with filters",
)
async def list_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    client_type: Optional[str] = Query(None, regex="^(buyer|seller|both)?$"),
    status: Optional[str] = Query(None, regex="^(active|inactive|archived)?$"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    sort_by: str = Query("created_at", regex="^(created_at|name|last_interaction)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClientListResponse:
    """
    List clients with filtering and pagination
    
    Query Parameters:
    - **skip**: Number of results to skip (default: 0)
    - **limit**: Number of results to return (default: 50, max: 100)
    - **client_type**: Filter by type (buyer, seller, both)
    - **status**: Filter by status (active, inactive, archived)
    - **search**: Search by first/last name or email
    - **sort_by**: Sort field (created_at, name, last_interaction)
    - **sort_order**: Sort order (asc, desc)
    
    All users can view clients, but Viewers see read-only data.
    """
    try:
        service = ClientService(db)
        
        clients, total = service.list_clients(
            organization_id=current_user.organization_id,
            skip=skip,
            limit=limit,
            client_type=client_type,
            status=status,
            search_query=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        
        return ClientListResponse(
            clients=[ClientResponse.model_validate(c) for c in clients],
            total=total,
            skip=skip,
            limit=limit,
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to list clients")

# ============================================================================
# GET Client Details
# ============================================================================

@router.get(
    "/{client_id}",
    response_model=ClientResponse,
    summary="Get client details",
)
async def get_client(
    client_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClientResponse:
    """
    Get detailed information about a specific client
    
    Includes:
    - Full profile information
    - Budget and preferences
    - Interaction history (access via separate endpoint)
    - Match history (access via separate endpoint)
    """
    try:
        service = ClientService(db)
        client = service.get_client(
            client_id=client_id,
            organization_id=current_user.organization_id,
        )
        
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        return ClientResponse.model_validate(client)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get client")

# ============================================================================
# UPDATE Client
# ============================================================================

@router.patch(
    "/{client_id}",
    response_model=ClientResponse,
    summary="Update client",
    description="Update client information (Agents can update own, Admins can update any)",
)
async def update_client(
    client_id: str,
    request: UpdateClientRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ClientResponse:
    """
    Update client profile information
    
    Fields that can be updated:
    - first_name, last_name, phone, email
    - client_type, status
    - notes, custom_fields
    
    Preferences should be updated via the /preferences endpoint.
    """
    try:
        service = ClientService(db)
        
        # Get client to verify ownership/permission
        client = service.get_client(client_id, current_user.organization_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        # Check permission: agents can only update their own clients
        if current_user.role == UserRole.AGENT and str(client.created_by_id) != current_user.user_id:
            raise HTTPException(
                status_code=403,
                detail="Agents can only update their own clients"
            )
        
        # Build update dict from non-None values
        update_dict = {k: v for k, v in request.model_dump().items() if v is not None}
        
        updated = service.update_client(
            client_id=client_id,
            organization_id=current_user.organization_id,
            **update_dict
        )
        
        return ClientResponse.model_validate(updated)
    
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to update client")

# ============================================================================
# UPDATE Client Preferences
# ============================================================================

@router.patch(
    "/{client_id}/preferences",
    response_model=ClientResponse,
    summary="Update client preferences",
    description="Update client's property search preferences",
)
async def update_preferences(
    client_id: str,
    request: PreferencesRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ClientResponse:
    """
    Update client's property preferences
    
    - **budget_min/max**: Price range
    - **property_types**: List of preferred types (e.g., ["single_family", "condo"])
    - **bedrooms**: Minimum bedrooms needed
    - **bathrooms**: Minimum bathrooms needed
    - **location_preferences**: Dict with cities/states/zips
    
    Example location_preferences:
    ```json
    {
      "cities": ["San Francisco", "Oakland"],
      "states": ["CA"],
      "zips": ["94102", "94103"]
    }
    ```
    """
    try:
        service = ClientService(db)
        
        client = service.get_client(client_id, current_user.organization_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        updated = service.update_preferences(
            client_id=client_id,
            organization_id=current_user.organization_id,
            budget_min=request.budget_min,
            budget_max=request.budget_max,
            property_types=request.property_types,
            bedrooms=request.bedrooms,
            bathrooms=request.bathrooms,
            location_preferences=request.location_preferences,
        )
        
        return ClientResponse.model_validate(updated)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to update preferences")

# ============================================================================
# CLIENT INTERACTIONS
# ============================================================================

@router.post(
    "/{client_id}/interactions",
    response_model=ClientInteractionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log client interaction",
    description="Record a client interaction (call, email, meeting, etc.)",
)
async def log_interaction(
    client_id: str,
    request: InteractionRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ClientInteractionResponse:
    """
    Log an interaction with a client
    
    Interaction Types:
    - **call**: Phone call with client
    - **email**: Email communication
    - **meeting**: In-person or video meeting
    - **showing**: Property showing
    - **offer**: Offer discussion
    
    All interactions are tracked for follow-up and activity metrics.
    """
    try:
        service = ClientService(db)
        
        # Verify client exists
        client = service.get_client(client_id, current_user.organization_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        interaction = service.log_interaction(
            client_id=client_id,
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
            interaction_type=request.interaction_type,
            description=request.description,
            property_id=request.property_id,
            notes=request.notes,
            duration_minutes=request.duration_minutes,
            follow_up_date=request.follow_up_date,
        )
        
        return ClientInteractionResponse.model_validate(interaction)
    
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to log interaction")

@router.get(
    "/{client_id}/interactions",
    response_model=List[ClientInteractionResponse],
    summary="Get client interactions",
    description="Retrieve client's interaction history",
)
async def get_interactions(
    client_id: str,
    limit: int = Query(50, ge=1, le=500),
    interaction_type: Optional[str] = Query(None),
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ClientInteractionResponse]:
    """
    Get interaction history for a client
    
    Query Parameters:
    - **limit**: Maximum number of interactions to return (default: 50)
    - **interaction_type**: Filter by type (call, email, meeting, showing, offer)
    
    Returns interactions sorted by most recent first.
    """
    try:
        service = ClientService(db)
        
        # Verify client exists
        client = service.get_client(client_id, current_user.organization_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        interactions = service.get_client_interactions(
            client_id=client_id,
            limit=limit,
            interaction_type=interaction_type,
        )
        
        return [ClientInteractionResponse.model_validate(i) for i in interactions]
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get interactions")

@router.get(
    "/admin/pending-follow-ups",
    response_model=List[ClientInteractionResponse],
    summary="Get pending follow-ups",
    description="Get all overdue follow-ups in organization",
)
async def get_pending_follow_ups(
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> List[ClientInteractionResponse]:
    """
    Get all pending follow-ups that are overdue
    
    Useful for:
    - Daily work prioritization
    - Follow-up reminders
    - Client engagement tracking
    
    Returns all overdue follow-ups sorted by date.
    """
    try:
        service = ClientService(db)
        
        follow_ups = service.get_pending_follow_ups(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id if current_user.role == UserRole.AGENT else None,
        )
        
        return [ClientInteractionResponse.model_validate(f) for f in follow_ups]
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get follow-ups")

# ============================================================================
# PROPERTY MATCHING
# ============================================================================

@router.post(
    "/{client_id}/match-properties",
    response_model=List[PropertyMatchResponse],
    summary="Find matching properties",
    description="Find properties matching client preferences",
)
async def find_matching_properties(
    client_id: str,
    limit: int = Query(20, ge=1, le=100),
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[PropertyMatchResponse]:
    """
    Find properties matching client's preferences
    
    Matching criteria:
    - Price range (budget_min/max)
    - Property type preferences
    - Bedroom/bathroom preferences
    - Location preferences (city/state)
    - Status = available
    
    Scoring:
    - Price match: 30 points
    - Type match: 25 points
    - Bedroom match: 20 points
    - Location match: 25 points
    - **Total: 0-100 points**
    
    Results sorted by match score (highest first).
    """
    try:
        service = ClientService(db)
        
        # Verify client exists
        client = service.get_client(client_id, current_user.organization_id)
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        
        # Check that client has preferences
        if not client.budget_min and not client.property_type_preferences and not client.bedroom_preferences:
            raise HTTPException(
                status_code=400,
                detail="Client must have preferences set before matching"
            )
        
        matches = service.find_matching_properties(
            client_id=client_id,
            organization_id=current_user.organization_id,
            limit=limit,
        )
        
        # Sort by score descending
        matches.sort(key=lambda m: m.match_score, reverse=True)
        
        return [PropertyMatchResponse.model_validate(m) for m in matches]
    
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to find matching properties")

# ============================================================================
# ARCHIVE & RESTORE
# ============================================================================

@router.post(
    "/{client_id}/archive",
    response_model=ClientResponse,
    summary="Archive client",
    description="Archive a client (soft delete)",
)
async def archive_client(
    client_id: str,
    reason: Optional[str] = Query(None),
    current_user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ClientResponse:
    """
    Archive a client (soft delete)
    
    Archived clients:
    - Are hidden from default listings
    - Can be restored later
    - All data is preserved
    - Appears in audit logs
    
    Only Admins can archive clients.
    """
    try:
        service = ClientService(db)
        
        client = service.archive_client(
            client_id=client_id,
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
            reason=reason,
        )
        
        return ClientResponse.model_validate(client)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to archive client")

@router.post(
    "/{client_id}/restore",
    response_model=ClientResponse,
    summary="Restore archived client",
    description="Restore an archived client",
)
async def restore_client(
    client_id: str,
    current_user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ClientResponse:
    """
    Restore an archived client
    
    Restores client to active status.
    All previous data remains intact.
    """
    try:
        service = ClientService(db)
        
        client = service.restore_client(
            client_id=client_id,
            organization_id=current_user.organization_id,
        )
        
        return ClientResponse.model_validate(client)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to restore client")

# ============================================================================
# STATISTICS
# ============================================================================

@router.get(
    "/admin/stats",
    response_model=ClientStatsResponse,
    summary="Get client statistics",
    description="Get organization-wide client statistics",
)
async def get_client_stats(
    current_user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ClientStatsResponse:
    """
    Get client statistics for the organization
    
    Metrics:
    - Total active clients
    - Buyers vs. Sellers breakdown
    - Percentage active
    - Recently engaged clients (last 30 days)
    """
    try:
        service = ClientService(db)
        
        stats = service.get_client_stats(
            organization_id=current_user.organization_id
        )
        
        return ClientStatsResponse(**stats)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get statistics")
