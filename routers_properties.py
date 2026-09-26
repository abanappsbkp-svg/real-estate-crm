"""
Properties Routes
CRUD operations, search, filtering, and property management endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime

from models import User, UserRole, Property
from models import APIModel
from services_properties import PropertyService
from middleware_auth import get_current_user, require_role
from db import get_db
from pydantic import BaseModel, Field

# ============================================================================
# Request/Response Models
# ============================================================================

class AddressSchema(APIModel):
    """Address information"""
    street: str
    city: str
    state: str
    zip_code: str
    country: str = "USA"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "street": "123 Main St",
                "city": "San Francisco",
                "state": "CA",
                "zip_code": "94105",
                "country": "USA",
                "latitude": 37.7749,
                "longitude": -122.4194,
            }
        }

class PropertyCreateRequest(APIModel):
    """Request to create new property"""
    address: AddressSchema
    property_type: str = Field(..., description="house, apartment, condo, etc.")
    list_price: float = Field(..., gt=0, description="Must be positive")
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    square_feet: Optional[float] = None
    lot_size: Optional[float] = None
    year_built: Optional[int] = None
    features: Optional[List[str]] = None
    description: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "address": {
                    "street": "123 Main St",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip_code": "94105",
                    "country": "USA",
                },
                "property_type": "house",
                "list_price": 1500000.0,
                "bedrooms": 4,
                "bathrooms": 3.5,
                "square_feet": 3500,
                "year_built": 2000,
                "features": ["pool", "garage", "patio"],
                "description": "Beautiful home in great location",
            }
        }

class PropertyUpdateRequest(APIModel):
    """Request to update property"""
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    square_feet: Optional[float] = None
    lot_size: Optional[float] = None
    features: Optional[List[str]] = None
    description: Optional[str] = None

class PropertyStatusUpdateRequest(APIModel):
    """Request to update property status"""
    status: str = Field(..., description="available, pending, sold, expired, withdrawn")
    notes: Optional[str] = None

class PropertyPriceUpdateRequest(APIModel):
    """Request to update property price"""
    new_price: float = Field(..., gt=0, description="Must be positive")
    reason: Optional[str] = None

class PropertyResponse(APIModel):
    """Property response DTO"""
    id: str
    organization_id: str
    listing_agent_id: str
    address: dict
    type: str
    status: str
    list_price: float
    bedrooms: Optional[int]
    bathrooms: Optional[float]
    square_feet: Optional[float]
    lot_size: Optional[float]
    year_built: Optional[int]
    features: List[str]
    description: Optional[str]
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True

class PropertyDetailResponse(PropertyResponse):
    """Detailed property response with history"""
    price_history: Optional[List[dict]] = None
    photos: Optional[List[dict]] = None
    created_at_display: Optional[str] = None
    
    class Config:
        from_attributes = True

# Create router
router = APIRouter(prefix="/properties", tags=["Properties"])

# ============================================================================
# Create Property (POST)
# ============================================================================

@router.post(
    "",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden - need agent role"},
    },
)
async def create_property(
    property_data: PropertyCreateRequest,
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Create a new property listing
    
    Requires Agent or Admin role
    
    Request body:
    ```json
    {
        "address": {
            "street": "123 Main St",
            "city": "San Francisco",
            "state": "CA",
            "zip_code": "94105"
        },
        "property_type": "house",
        "list_price": 1500000.0,
        "bedrooms": 4,
        "bathrooms": 3.5,
        "square_feet": 3500,
        "features": ["pool", "garage"]
    }
    ```
    
    Returns:
    ```json
    {
        "status": "success",
        "data": {
            "property": { ... }
        }
    }
    ```
    """
    try:
        property_service = PropertyService(db)
        
        property_obj = property_service.create_property(
            organization_id=str(current_user.organization_id),
            listing_agent_id=str(current_user.id),
            address=property_data.address.model_dump(),
            property_type=property_data.property_type,
            list_price=property_data.list_price,
            bedrooms=property_data.bedrooms,
            bathrooms=property_data.bathrooms,
            square_feet=property_data.square_feet,
            lot_size=property_data.lot_size,
            year_built=property_data.year_built,
            features=property_data.features,
            description=property_data.description,
        )
        
        return {
            "status": "success",
            "message": "Property created successfully",
            "data": {
                "property": PropertyResponse.model_validate(property_obj),
            },
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# List Properties (GET)
# ============================================================================

@router.get(
    "",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def list_properties(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=500, description="Number of records to return"),
    status: Optional[str] = Query(None, description="Filter by status"),
    property_type: Optional[str] = Query(None, description="Filter by type"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum price"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum price"),
    min_bedrooms: Optional[int] = Query(None, ge=0, description="Minimum bedrooms"),
    city: Optional[str] = Query(None, description="Filter by city"),
    state: Optional[str] = Query(None, description="Filter by state"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List properties with filters and pagination
    
    Query parameters:
    - skip: Number of records to skip (default: 0)
    - limit: Records per page (default: 50, max: 500)
    - status: available, pending, sold, expired, withdrawn
    - property_type: house, apartment, condo, etc.
    - min_price: Minimum list price
    - max_price: Maximum list price
    - min_bedrooms: Minimum bedrooms
    - city: Filter by city name
    - state: Filter by state
    - sort_by: created_at, list_price, bedrooms
    - sort_order: asc or desc
    
    Returns paginated list with metadata
    """
    try:
        property_service = PropertyService(db)
        
        properties, total = property_service.list_properties(
            organization_id=str(current_user.organization_id),
            skip=skip,
            limit=limit,
            status=status,
            property_type=property_type,
            min_price=min_price,
            max_price=max_price,
            min_bedrooms=min_bedrooms,
            city=city,
            state=state,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        
        return {
            "status": "success",
            "data": {
                "properties": [PropertyResponse.model_validate(p) for p in properties],
                "pagination": {
                    "skip": skip,
                    "limit": limit,
                    "total": total,
                    "pages": (total + limit - 1) // limit,
                },
            },
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# Get Property Details (GET)
# ============================================================================

@router.get(
    "/{property_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Property not found"}},
)
async def get_property_details(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get detailed property information including price history and photos
    
    Returns:
    ```json
    {
        "status": "success",
        "data": {
            "property": {
                "id": "uuid",
                "address": { ... },
                "type": "house",
                "status": "available",
                "list_price": 1500000.0,
                "price_history": [ ... ],
                "photos": [ ... ]
            }
        }
    }
    ```
    """
    try:
        property_service = PropertyService(db)
        
        property_obj = property_service.get_property(
            property_id=property_id,
            organization_id=str(current_user.organization_id),
        )
        
        if not property_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found",
            )
        
        return {
            "status": "success",
            "data": {
                "property": PropertyDetailResponse.model_validate(property_obj),
            },
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# Update Property (PATCH)
# ============================================================================

@router.patch(
    "/{property_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Property not found"},
        403: {"description": "Forbidden - not listing agent"},
    },
)
async def update_property(
    property_id: str,
    update_data: PropertyUpdateRequest,
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Update property information (bedrooms, bathrooms, features, description)
    
    Note: Only the listing agent or admin can update
    
    Request body:
    ```json
    {
        "bedrooms": 5,
        "bathrooms": 4.5,
        "features": ["pool", "garage", "renovated kitchen"]
    }
    ```
    """
    try:
        property_service = PropertyService(db)
        
        # Check if agent owns the property
        property_obj = property_service.get_property(
            property_id=property_id,
            organization_id=str(current_user.organization_id),
        )
        
        if not property_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found",
            )
        
        if (property_obj.listing_agent_id != current_user.id and 
            current_user.role != UserRole.ADMIN.value):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only listing agent or admin can update",
            )
        
        # Update
        property_obj = property_service.update_property(
            property_id=property_id,
            organization_id=str(current_user.organization_id),
            **update_data.model_dump(exclude_unset=True),
        )
        
        return {
            "status": "success",
            "message": "Property updated successfully",
            "data": {
                "property": PropertyResponse.model_validate(property_obj),
            },
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# Update Status (PATCH)
# ============================================================================

@router.patch(
    "/{property_id}/status",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Property not found"}},
)
async def update_property_status(
    property_id: str,
    status_data: PropertyStatusUpdateRequest,
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Change property status (available → pending → sold)
    
    Valid statuses:
    - available
    - pending (offer received)
    - sold
    - expired (listing expired)
    - withdrawn (delisted)
    
    Request body:
    ```json
    {
        "status": "pending",
        "notes": "Accepted offer from buyer"
    }
    ```
    """
    try:
        property_service = PropertyService(db)
        
        property_obj = property_service.update_status(
            property_id=property_id,
            organization_id=str(current_user.organization_id),
            new_status=status_data.status,
            user_id=str(current_user.id),
            notes=status_data.notes,
        )
        
        return {
            "status": "success",
            "message": f"Property status changed to {status_data.status}",
            "data": {
                "property": PropertyResponse.model_validate(property_obj),
            },
        }
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# Update Price (PATCH)
# ============================================================================

@router.patch(
    "/{property_id}/price",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Property not found"}},
)
async def update_property_price(
    property_id: str,
    price_data: PropertyPriceUpdateRequest,
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Update property price and record in history
    
    Reasons for price change:
    - price_reduction
    - market_adjustment
    - buyer_request
    - competitive_analysis
    - manual_adjustment
    
    Request body:
    ```json
    {
        "new_price": 1450000.0,
        "reason": "price_reduction"
    }
    ```
    """
    try:
        property_service = PropertyService(db)
        
        property_obj = property_service.update_price(
            property_id=property_id,
            organization_id=str(current_user.organization_id),
            new_price=price_data.new_price,
            user_id=str(current_user.id),
            reason=price_data.reason,
        )
        
        return {
            "status": "success",
            "message": f"Price updated to ${price_data.new_price:,.2f}",
            "data": {
                "property": PropertyResponse.model_validate(property_obj),
            },
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# Delete Property (DELETE) - Soft Delete
# ============================================================================

@router.delete(
    "/{property_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Property not found"}},
)
async def delete_property(
    property_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Soft delete property (marks as deleted but doesn't remove from database)
    
    Admin only
    
    Returns:
    ```json
    {
        "status": "success",
        "message": "Property deleted successfully"
    }
    ```
    """
    try:
        property_service = PropertyService(db)
        
        property_service.delete_property(
            property_id=property_id,
            organization_id=str(current_user.organization_id),
            user_id=str(current_user.id),
            reason="Admin deletion",
        )
        
        return {
            "status": "success",
            "message": "Property deleted successfully",
        }
    
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# Search Properties (GET)
# ============================================================================

@router.get(
    "/search/text",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def search_properties(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, le=100, description="Max results"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Full-text search properties by address and description
    
    Query parameters:
    - q: Search query (min 2 characters)
    - limit: Max results (default: 20, max: 100)
    
    Searches in:
    - Address (street, city, state)
    - Description
    """
    try:
        property_service = PropertyService(db)
        
        properties = property_service.search_properties(
            organization_id=str(current_user.organization_id),
            query=q,
            limit=limit,
        )
        
        return {
            "status": "success",
            "data": {
                "properties": [PropertyResponse.model_validate(p) for p in properties],
                "total": len(properties),
                "query": q,
            },
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# Get Property History (GET)
# ============================================================================

@router.get(
    "/{property_id}/history",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Property not found"}},
)
async def get_property_history(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get property audit trail and status change history
    
    Returns all changes made to the property including:
    - Status changes with timestamps
    - Price adjustments
    - Feature updates
    - Who made each change
    """
    try:
        property_service = PropertyService(db)
        
        # Verify property exists
        property_obj = property_service.get_property(
            property_id=property_id,
            organization_id=str(current_user.organization_id),
        )
        
        if not property_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found",
            )
        
        history = property_service.get_property_history(property_id)
        audit_log = property_service.get_audit_log(property_id)
        
        return {
            "status": "success",
            "data": {
                "status_history": [
                    {
                        "changed_at": h.changed_at.isoformat(),
                        "status_from": h.status_from,
                        "status_to": h.status_to,
                        "reason": h.reason,
                        "changed_by_id": str(h.changed_by_id),
                    }
                    for h in history
                ],
                "audit_log": [
                    {
                        "created_at": log.created_at.isoformat(),
                        "action": log.action,
                        "user_id": str(log.user_id) if log.user_id else None,
                        "old_values": log.old_values,
                        "new_values": log.new_values,
                    }
                    for log in audit_log
                ],
            },
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

# ============================================================================
# Get Statistics (GET)
# ============================================================================

@router.get(
    "/stats/organization",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def get_organization_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get organization property statistics
    
    Returns:
    - Total properties
    - Available, pending, sold counts
    - Average price
    - Percentages by status
    """
    try:
        property_service = PropertyService(db)
        
        stats = property_service.get_property_stats(
            organization_id=str(current_user.organization_id),
        )
        
        return {
            "status": "success",
            "data": {
                "statistics": stats,
            },
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
