"""
Example API Router: Properties
This demonstrates how to implement REST endpoints following the established patterns.

To use this:
1. Copy this to routers/properties.py
2. Import and include in main.py:
   from routers import properties
   app.include_router(properties.router, prefix="/api/v1")
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import uuid

from models import (
    Property, PropertySchema, PropertyCreateSchema, PropertyStatus,
    PropertyHistory, User, UserRole, Organization
)
from main import PropertyService, get_db
from config import settings

# Create router
router = APIRouter(tags=["Properties"])

# ============================================================================
# Dependencies
# ============================================================================

async def get_current_user(db: Session = Depends(get_db)) -> User:
    """
    Get current user from JWT token.
    TODO: Implement JWT validation in auth middleware
    """
    # For now, this is a placeholder
    # In production, extract from JWT token in Authorization header
    raise NotImplementedError("Implement JWT token validation")

async def get_current_org(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Organization:
    """Get current user's organization"""
    org = db.query(Organization).filter(
        Organization.id == current_user.organization_id
    ).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    return org

def require_role(*roles: UserRole):
    """Decorator to require specific roles"""
    async def check_role(current_user: User = Depends(get_current_user)):
        if current_user.role not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions"
            )
        return current_user
    return check_role

# ============================================================================
# List Properties
# ============================================================================

@router.get("/properties", response_model=dict)
async def list_properties(
    current_user: User = Depends(get_current_user),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
    # Filters
    status: Optional[PropertyStatus] = Query(None),
    type: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    bedrooms: Optional[int] = Query(None),
    city: Optional[str] = Query(None),
    # Pagination
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=settings.MAX_PAGE_SIZE),
    # Sorting
    sort_by: str = Query("updated_at"),
    sort_desc: bool = Query(True),
):
    """
    List properties with filtering and pagination.
    
    Query Parameters:
    - status: available, reserved, sold, rented, delisted
    - type: apartment, house, commercial, land
    - min_price/max_price: Price range filter
    - bedrooms: Number of bedrooms
    - city: Filter by city
    - page: Page number (1-based)
    - page_size: Results per page (1-1000)
    - sort_by: Field to sort by (default: updated_at)
    - sort_desc: Sort descending (default: true)
    
    Returns:
    - data: List of properties
    - pagination: Total, page, page_size, total_pages
    - filters: Applied filters (for UI display)
    """
    try:
        service = PropertyService(db)
        
        # Get properties with filters
        properties, total = service.search_properties(
            organization_id=str(current_org.id),
            status=status,
            type=type,
            min_price=min_price,
            max_price=max_price,
            bedrooms=bedrooms,
            skip=(page - 1) * page_size,
            limit=page_size,
        )
        
        # Apply city filter if needed (JSONB query)
        if city:
            properties = [
                p for p in properties 
                if p.address and p.address.get("city") == city
            ]
        
        # Convert to schemas
        properties_data = [PropertySchema.model_validate(p) for p in properties]
        
        return {
            "status": "success",
            "data": properties_data,
            "pagination": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            },
            "filters": {
                "status": status.value if status else None,
                "type": type,
                "min_price": min_price,
                "max_price": max_price,
                "bedrooms": bedrooms,
                "city": city,
            }
        }
    
    except Exception as e:
        # Log exception
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Get Property Details
# ============================================================================

@router.get("/properties/{property_id}", response_model=dict)
async def get_property(
    property_id: str,
    current_user: User = Depends(get_current_user),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Get detailed information about a specific property.
    
    Includes:
    - Property details
    - Price history
    - Photos
    - Agent info
    - Recent interactions
    """
    try:
        service = PropertyService(db)
        
        # Get property
        property_obj = service.get_property_details(property_id)
        
        if not property_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        # Check organization access
        if property_obj.organization_id != current_org.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        # Build response with relationships
        return {
            "status": "success",
            "data": {
                **PropertySchema.model_validate(property_obj).model_dump(),
                "agent": {
                    "id": str(property_obj.listing_agent.id),
                    "name": property_obj.listing_agent.full_name,
                } if property_obj.listing_agent else None,
                "history": [
                    {
                        "id": str(h.id),
                        "field": h.field_name,
                        "old_value": h.old_value,
                        "new_value": h.new_value,
                        "change_type": h.change_type,
                        "reason": h.change_reason,
                        "changed_at": h.created_at.isoformat(),
                        "changed_by": h.changed_by_user.full_name if h.changed_by_user else "System",
                    }
                    for h in property_obj.history
                ],
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Create Property
# ============================================================================

@router.post("/properties", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_property(
    data: PropertyCreateSchema,
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Create a new property listing.
    
    Only agents and admins can create properties.
    
    Request Body:
    {
        "type": "house",
        "address": {
            "street": "123 Main St",
            "city": "Los Angeles",
            "state": "CA",
            "zip": "90001",
            "country": "USA"
        },
        "list_price": 500000,
        "bedrooms": 3,
        "bathrooms": 2.5,
        "description": "Beautiful home...",
        "features": {
            "pool": true,
            "garage": true
        }
    }
    """
    try:
        service = PropertyService(db)
        
        # Create property
        property_obj = service.create_property(
            organization_id=str(current_org.id),
            listing_agent_id=str(current_user.id),
            data=data,
        )
        
        return {
            "status": "success",
            "message": "Property created successfully",
            "data": PropertySchema.model_validate(property_obj),
        }
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Update Property
# ============================================================================

@router.patch("/properties/{property_id}", response_model=dict)
async def update_property(
    property_id: str,
    data: PropertyCreateSchema,
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Update property information.
    
    Only the listing agent or admin can update properties.
    All changes are audited.
    """
    try:
        # Get property
        property_obj = db.query(Property).filter(
            Property.id == uuid.UUID(property_id),
            Property.organization_id == current_org.id,
            Property.deleted_at.is_(None),
        ).first()
        
        if not property_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        # Check authorization
        if (property_obj.listing_agent_id != current_user.id and 
            current_user.role != UserRole.ADMIN.value):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only listing agent can update"
            )
        
        # Update fields
        update_fields = data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            if value is not None:
                setattr(property_obj, field, value)
        
        property_obj.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(property_obj)
        
        return {
            "status": "success",
            "message": "Property updated successfully",
            "data": PropertySchema.model_validate(property_obj),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Update Property Status
# ============================================================================

@router.patch("/properties/{property_id}/status", response_model=dict)
async def update_property_status(
    property_id: str,
    status_data: dict,  # { "status": "sold", "reason": "Sold to buyer X" }
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Change property status (available, reserved, sold, rented, delisted).
    
    Status changes are audited and tracked.
    """
    try:
        service = PropertyService(db)
        
        new_status = PropertyStatus(status_data["status"])
        reason = status_data.get("reason")
        
        # Update status
        property_obj = service.update_property_status(
            property_id=property_id,
            new_status=new_status,
            reason=reason,
            changed_by=str(current_user.id),
        )
        
        return {
            "status": "success",
            "message": f"Property status changed to {new_status.value}",
            "data": PropertySchema.model_validate(property_obj),
        }
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Update Price
# ============================================================================

@router.patch("/properties/{property_id}/price", response_model=dict)
async def update_price(
    property_id: str,
    price_data: dict,  # { "price": 450000, "reason": "Market adjustment" }
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Update property price.
    
    Maintains price history for analysis.
    """
    try:
        service = PropertyService(db)
        
        new_price = price_data["price"]
        reason = price_data.get("reason")
        
        if new_price <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Price must be greater than 0"
            )
        
        # Update price
        property_obj = service.update_price(
            property_id=property_id,
            new_price=new_price,
            reason=reason,
            changed_by=str(current_user.id),
        )
        
        return {
            "status": "success",
            "message": "Price updated successfully",
            "data": PropertySchema.model_validate(property_obj),
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Delete Property (Soft Delete)
# ============================================================================

@router.delete("/properties/{property_id}", response_model=dict)
async def delete_property(
    property_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Soft delete a property.
    
    Only admins can delete. Data is retained for audit trail.
    """
    try:
        # Get property
        property_obj = db.query(Property).filter(
            Property.id == uuid.UUID(property_id),
            Property.organization_id == current_org.id,
            Property.deleted_at.is_(None),
        ).first()
        
        if not property_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        # Soft delete
        property_obj.deleted_at = datetime.utcnow()
        db.commit()
        
        return {
            "status": "success",
            "message": "Property deleted successfully",
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Upload Photos
# ============================================================================

@router.post("/properties/{property_id}/photos", response_model=dict)
async def upload_photos(
    property_id: str,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """
    Upload photos for a property.
    
    - Accepts multiple files
    - Stores on S3/MinIO
    - Updates property record
    
    TODO: Implement file upload to S3
    """
    try:
        # Get property
        property_obj = db.query(Property).filter(
            Property.id == uuid.UUID(property_id),
            Property.organization_id == current_org.id,
            Property.deleted_at.is_(None),
        ).first()
        
        if not property_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        # TODO: Upload to S3
        # - Validate file types (JPEG, PNG only)
        # - Generate thumbnails
        # - Store URLs in database
        # - Update primary_photo_url if first photo
        
        return {
            "status": "success",
            "message": f"Uploaded {len(files)} photos",
            "photos": [
                {
                    "url": f"s3://bucket/property/{property_id}/photo_{i}.jpg",
                    "order": i,
                }
                for i in range(len(files))
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Get Property Audit Trail
# ============================================================================

@router.get("/properties/{property_id}/history", response_model=dict)
async def get_property_history(
    property_id: str,
    current_user: User = Depends(get_current_user),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """
    Get complete audit trail for a property.
    
    Shows all changes: status, price, description, etc.
    """
    try:
        property_obj = db.query(Property).filter(
            Property.id == uuid.UUID(property_id),
            Property.organization_id == current_org.id,
        ).first()
        
        if not property_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Property not found"
            )
        
        # Get history
        history = db.query(PropertyHistory).filter(
            PropertyHistory.property_id == uuid.UUID(property_id),
        ).order_by(
            PropertyHistory.created_at.desc()
        ).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        
        total = db.query(PropertyHistory).filter(
            PropertyHistory.property_id == uuid.UUID(property_id),
        ).count()
        
        return {
            "status": "success",
            "data": [
                {
                    "id": str(h.id),
                    "field": h.field_name,
                    "old_value": h.old_value,
                    "new_value": h.new_value,
                    "change_type": h.change_type,
                    "reason": h.change_reason,
                    "changed_by": h.changed_by_user.full_name if h.changed_by_user else "System",
                    "timestamp": h.created_at.isoformat(),
                }
                for h in history
            ],
            "pagination": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# ============================================================================
# Search Properties (Full-text Search)
# ============================================================================

@router.get("/properties/search/text", response_model=dict)
async def search_properties_text(
    q: str = Query(..., min_length=2),
    current_user: User = Depends(get_current_user),
    current_org: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
    limit: int = Query(20, le=100),
):
    """
    Full-text search for properties.
    
    Searches: address, description, MLS number, tags
    """
    try:
        # TODO: Implement full-text search
        # Use PostgreSQL full-text search or Elasticsearch
        # Search in: address (JSONB), description, tags, mls_number
        
        return {
            "status": "success",
            "data": [],
            "query": q,
        }
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

"""
This example router demonstrates:
1. RESTful endpoint patterns
2. Dependency injection for auth and org context
3. Error handling with proper status codes
4. Request/response validation with Pydantic
5. Database operations via service layer
6. Audit trail creation
7. Pagination support
8. Query parameters for filtering
9. Authorization checks
10. Documentation with docstrings

Follow this pattern for:
- routers/clients.py
- routers/deals.py
- routers/calls.py
- routers/reports.py
"""
