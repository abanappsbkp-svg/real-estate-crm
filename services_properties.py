"""
Properties Service
Business logic for property management, search, and lifecycle
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, cast, Text
import uuid
from models import as_uuid

from models import (
    Property, PropertyStatus, PropertyHistory, Organization,
    User, PropertyMatch, AuditLog
)

class PropertyService:
    """Service for property management and operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ========================================================================
    # Create & Register Properties
    # ========================================================================
    
    def create_property(
        self,
        organization_id: str,
        listing_agent_id: str,
        address: Dict[str, Any],
        property_type: str,
        status: str = "available",
        list_price: float = 0.0,
        bedrooms: Optional[int] = None,
        bathrooms: Optional[float] = None,
        square_feet: Optional[float] = None,
        lot_size: Optional[float] = None,
        year_built: Optional[int] = None,
        features: Optional[List[str]] = None,
        description: Optional[str] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> Property:
        """
        Create a new property listing
        
        Args:
            organization_id: Organization UUID
            listing_agent_id: Agent listing the property
            address: Dict with street, city, state, zip, country
            property_type: apartment, house, condo, etc.
            status: available, pending, sold, expired, withdrawn
            list_price: Listing price
            bedrooms: Number of bedrooms
            bathrooms: Number of bathrooms
            square_feet: Building square footage
            lot_size: Lot size in square feet
            year_built: Year property was built
            features: List of features (pool, garage, fireplace, etc.)
            description: Full property description
            custom_fields: Additional custom metadata
        
        Returns:
            Created Property object
        """
        property_obj = Property(
            organization_id=as_uuid(organization_id),
            listing_agent_id=as_uuid(listing_agent_id),
            address=address,
            type=property_type,
            status=status,
            list_price=list_price,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            square_feet=square_feet,
            lot_size=lot_size,
            year_built=year_built,
            features=features or [],
            description=description,
            custom_fields=custom_fields or {},
        )
        
        self.db.add(property_obj)
        self.db.commit()
        self.db.refresh(property_obj)
        
        # Log creation
        self._log_audit(
            organization_id=organization_id,
            user_id=listing_agent_id,
            action="property_created",
            entity_type="property",
            entity_id=str(property_obj.id),
            new_values={
                "address": address,
                "type": property_type,
                "status": status,
                "price": float(list_price),
            },
        )
        
        # Initialize price history
        self.add_price_history(str(property_obj.id), list_price, "initial_listing")
        
        return property_obj
    
    # ========================================================================
    # Read & Retrieve Properties
    # ========================================================================
    
    def get_property(self, property_id: str, organization_id: Optional[str] = None) -> Optional[Property]:
        """Get property by ID"""
        query = self.db.query(Property).filter(
            Property.id == as_uuid(property_id),
            Property.deleted_at.is_(None),
        )
        
        if organization_id:
            query = query.filter(Property.organization_id == as_uuid(organization_id))
        
        return query.first()
    
    def list_properties(
        self,
        organization_id: str,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        property_type: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_bedrooms: Optional[int] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[List[Property], int]:
        """
        List properties with filters
        
        Args:
            organization_id: Organization UUID
            skip: Number of records to skip
            limit: Number of records to return
            status: Filter by status (available, pending, sold)
            property_type: Filter by type (house, apartment, etc.)
            min_price: Minimum list price
            max_price: Maximum list price
            min_bedrooms: Minimum bedrooms
            city: Filter by city
            state: Filter by state
            sort_by: Field to sort by (created_at, list_price, bedrooms)
            sort_order: asc or desc
        
        Returns:
            Tuple of (properties list, total count)
        """
        query = self.db.query(Property).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.deleted_at.is_(None),
        )
        
        # Apply filters
        if status:
            query = query.filter(Property.status == status)
        
        if property_type:
            query = query.filter(Property.type == property_type)
        
        if min_price is not None:
            query = query.filter(Property.list_price >= min_price)
        
        if max_price is not None:
            query = query.filter(Property.list_price <= max_price)
        
        if min_bedrooms is not None:
            query = query.filter(Property.bedrooms >= min_bedrooms)
        
        if city:
            query = query.filter(
                func.lower(Property.address["city"].astext) == city.lower()
            )
        
        if state:
            query = query.filter(
                func.lower(Property.address["state"].astext) == state.lower()
            )
        
        # Count total
        total = query.count()
        
        # Sort
        if sort_by == "created_at":
            query = query.order_by(
                Property.created_at.desc() if sort_order == "desc" else Property.created_at.asc()
            )
        elif sort_by == "list_price":
            query = query.order_by(
                Property.list_price.desc() if sort_order == "desc" else Property.list_price.asc()
            )
        elif sort_by == "bedrooms":
            query = query.order_by(
                Property.bedrooms.desc() if sort_order == "desc" else Property.bedrooms.asc()
            )
        
        # Pagination
        properties = query.offset(skip).limit(limit).all()
        
        return properties, total
    
    # ========================================================================
    # Update Property
    # ========================================================================
    
    def update_property(
        self,
        property_id: str,
        organization_id: str,
        **kwargs
    ) -> Property:
        """
        Update property information
        
        Args:
            property_id: Property UUID
            organization_id: Organization UUID (for auth check)
            **kwargs: Fields to update (address, bedrooms, bathrooms, features, etc.)
        
        Returns:
            Updated Property object
        """
        property_obj = self.get_property(property_id, organization_id)
        
        if not property_obj:
            raise ValueError("Property not found")
        
        old_values = {}
        new_values = {}
        
        # Update allowed fields
        allowed_fields = {
            'address', 'bedrooms', 'bathrooms', 'square_feet', 'lot_size',
            'year_built', 'features', 'description', 'custom_fields'
        }
        
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                old_values[field] = getattr(property_obj, field)
                setattr(property_obj, field, value)
                new_values[field] = value
        
        property_obj.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(property_obj)
        
        # Log update
        if new_values:
            self._log_audit(
                organization_id=organization_id,
                user_id=None,  # Would come from request context
                action="property_updated",
                entity_type="property",
                entity_id=property_id,
                old_values=old_values,
                new_values=new_values,
            )
        
        return property_obj
    
    # ========================================================================
    # Property Status Management
    # ========================================================================
    
    def update_status(
        self,
        property_id: str,
        organization_id: str,
        new_status: str,
        user_id: str,
        notes: Optional[str] = None,
    ) -> Property:
        """
        Change property status (available → pending → sold, etc.)
        
        Args:
            property_id: Property UUID
            organization_id: Organization UUID
            new_status: New status value
            user_id: User making the change
            notes: Optional notes about the status change
        
        Returns:
            Updated Property object
        """
        # Validate status
        valid_statuses = [s.value for s in PropertyStatus]
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of: {valid_statuses}")
        
        property_obj = self.get_property(property_id, organization_id)
        
        if not property_obj:
            raise ValueError("Property not found")
        
        old_status = property_obj.status
        property_obj.status = new_status
        property_obj.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(property_obj)
        
        # Create status history record
        history = PropertyHistory(
            property_id=as_uuid(property_id),
            changed_by_id=as_uuid(user_id),
            status_from=old_status,
            status_to=new_status,
            reason=notes,
        )
        self.db.add(history)
        self.db.commit()
        
        # Log change
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="property_status_changed",
            entity_type="property",
            entity_id=property_id,
            old_values={"status": old_status},
            new_values={"status": new_status},
        )
        
        return property_obj
    
    # ========================================================================
    # Price Management
    # ========================================================================
    
    def update_price(
        self,
        property_id: str,
        organization_id: str,
        new_price: float,
        user_id: str,
        reason: Optional[str] = None,
    ) -> Property:
        """
        Update property price and record history
        
        Args:
            property_id: Property UUID
            organization_id: Organization UUID
            new_price: New price
            user_id: User making the change
            reason: Reason for price change (price_reduction, market_adjustment, etc.)
        
        Returns:
            Updated Property object
        """
        property_obj = self.get_property(property_id, organization_id)
        
        if not property_obj:
            raise ValueError("Property not found")
        
        old_price = property_obj.list_price
        property_obj.list_price = new_price
        property_obj.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(property_obj)
        
        # Add to price history
        self.add_price_history(
            property_id=property_id,
            price=new_price,
            reason=reason or "manual_adjustment",
            changed_by_id=user_id,
        )
        
        # Log change
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="property_price_changed",
            entity_type="property",
            entity_id=property_id,
            old_values={"price": float(old_price)},
            new_values={"price": float(new_price)},
        )
        
        return property_obj
    
    def add_price_history(
        self,
        property_id: str,
        price: float,
        reason: str = "manual_adjustment",
        changed_by_id: Optional[str] = None,
    ):
        """Add entry to property price history"""
        property_obj = self.db.query(Property).filter(
            Property.id == as_uuid(property_id)
        ).first()
        
        if not property_obj:
            return
        
        # Add to JSONB price_history array
        if not property_obj.price_history:
            property_obj.price_history = []
        
        property_obj.price_history.append({
            "price": float(price),
            "changed_at": datetime.utcnow().isoformat(),
            "changed_by": changed_by_id,
            "reason": reason,
        })
        
        self.db.commit()
    
    def get_price_history(self, property_id: str) -> List[Dict[str, Any]]:
        """Get property price history"""
        property_obj = self.db.query(Property).filter(
            Property.id == as_uuid(property_id)
        ).first()
        
        if not property_obj or not property_obj.price_history:
            return []
        
        return property_obj.price_history
    
    # ========================================================================
    # Search & Filter
    # ========================================================================
    
    def search_properties(
        self,
        organization_id: str,
        query: str,
        limit: int = 20,
    ) -> List[Property]:
        """
        Full-text search properties by address, description
        
        Args:
            organization_id: Organization UUID
            query: Search query
            limit: Max results
        
        Returns:
            List of matching properties
        """
        # Simple text search on description and address
        search_term = f"%{query}%"
        
        properties = self.db.query(Property).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.deleted_at.is_(None),
            or_(
                Property.description.ilike(search_term),
                cast(Property.address, Text).ilike(search_term),
            ),
        ).limit(limit).all()
        
        return properties
    
    def find_similar_properties(
        self,
        property_id: str,
        organization_id: str,
        limit: int = 10,
    ) -> List[Property]:
        """
        Find similar properties (same type, similar price, same area)
        
        Args:
            property_id: Property UUID
            organization_id: Organization UUID
            limit: Max similar properties
        
        Returns:
            List of similar properties
        """
        property_obj = self.get_property(property_id, organization_id)
        
        if not property_obj:
            return []
        
        # Calculate price range (±20%)
        price_variance = property_obj.list_price * 0.2
        min_price = property_obj.list_price - price_variance
        max_price = property_obj.list_price + price_variance
        
        # Get city from address
        city = property_obj.address.get("city", "")
        
        similar = self.db.query(Property).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.id != as_uuid(property_id),
            Property.type == property_obj.type,
            Property.list_price.between(min_price, max_price),
            func.lower(Property.address["city"].astext) == city.lower(),
            Property.deleted_at.is_(None),
        ).limit(limit).all()
        
        return similar
    
    # ========================================================================
    # Delete & Soft Delete
    # ========================================================================
    
    def delete_property(
        self,
        property_id: str,
        organization_id: str,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Soft delete property (mark as deleted, don't remove from DB)
        
        Args:
            property_id: Property UUID
            organization_id: Organization UUID
            user_id: User deleting the property
            reason: Reason for deletion
        
        Returns:
            True if successful
        """
        property_obj = self.get_property(property_id, organization_id)
        
        if not property_obj:
            raise ValueError("Property not found")
        
        property_obj.deleted_at = datetime.utcnow()
        self.db.commit()
        
        # Log deletion
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="property_deleted",
            entity_type="property",
            entity_id=property_id,
            new_values={"reason": reason or "no reason provided"},
        )
        
        return True
    
    def restore_property(self, property_id: str, organization_id: str) -> Property:
        """Restore a soft-deleted property"""
        property_obj = self.db.query(Property).filter(
            Property.id == as_uuid(property_id),
            Property.organization_id == as_uuid(organization_id),
        ).first()
        
        if not property_obj:
            raise ValueError("Property not found")
        
        property_obj.deleted_at = None
        self.db.commit()
        self.db.refresh(property_obj)
        
        return property_obj
    
    # ========================================================================
    # Photos & Media
    # ========================================================================
    
    def add_photo(
        self,
        property_id: str,
        photo_url: str,
        caption: Optional[str] = None,
        is_primary: bool = False,
    ):
        """Add photo to property"""
        property_obj = self.db.query(Property).filter(
            Property.id == as_uuid(property_id)
        ).first()
        
        if not property_obj:
            return
        
        if not property_obj.custom_fields:
            property_obj.custom_fields = {}
        
        if "photos" not in property_obj.custom_fields:
            property_obj.custom_fields["photos"] = []
        
        photo = {
            "url": photo_url,
            "caption": caption,
            "is_primary": is_primary,
            "uploaded_at": datetime.utcnow().isoformat(),
        }
        
        # If marking as primary, unmark others
        if is_primary:
            for p in property_obj.custom_fields["photos"]:
                p["is_primary"] = False
        
        property_obj.custom_fields["photos"].append(photo)
        self.db.commit()
    
    def get_photos(self, property_id: str) -> List[Dict[str, Any]]:
        """Get property photos"""
        property_obj = self.db.query(Property).filter(
            Property.id == as_uuid(property_id)
        ).first()
        
        if not property_obj or not property_obj.custom_fields:
            return []
        
        return property_obj.custom_fields.get("photos", [])
    
    # ========================================================================
    # Audit & History
    # ========================================================================
    
    def get_property_history(self, property_id: str) -> List[PropertyHistory]:
        """Get property status change history"""
        return self.db.query(PropertyHistory).filter(
            PropertyHistory.property_id == as_uuid(property_id)
        ).order_by(PropertyHistory.changed_at.desc()).all()
    
    def get_audit_log(
        self,
        property_id: str,
        limit: int = 50,
    ) -> List[AuditLog]:
        """Get audit log for property"""
        return self.db.query(AuditLog).filter(
            AuditLog.entity_id == as_uuid(property_id),
            AuditLog.entity_type == "property",
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()
    
    # ========================================================================
    # Statistics & Analytics
    # ========================================================================
    
    def get_property_stats(self, organization_id: str) -> Dict[str, Any]:
        """Get property statistics for organization"""
        total = self.db.query(Property).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.deleted_at.is_(None),
        ).count()
        
        available = self.db.query(Property).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.status == PropertyStatus.AVAILABLE.value,
            Property.deleted_at.is_(None),
        ).count()
        
        pending = self.db.query(Property).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.status == PropertyStatus.PENDING.value,
            Property.deleted_at.is_(None),
        ).count()
        
        sold = self.db.query(Property).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.status == PropertyStatus.SOLD.value,
            Property.deleted_at.is_(None),
        ).count()
        
        # Average price
        avg_price_result = self.db.query(func.avg(Property.list_price)).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.deleted_at.is_(None),
        ).first()
        
        avg_price = float(avg_price_result[0]) if avg_price_result[0] else 0.0
        
        return {
            "total_properties": total,
            "available": available,
            "pending": pending,
            "sold": sold,
            "average_price": avg_price,
            "percentage_available": (available / total * 100) if total > 0 else 0,
            "percentage_pending": (pending / total * 100) if total > 0 else 0,
            "percentage_sold": (sold / total * 100) if total > 0 else 0,
        }
    
    # ========================================================================
    # Private Methods
    # ========================================================================
    
    def _log_audit(
        self,
        organization_id: str,
        user_id: Optional[str],
        action: str,
        entity_type: str = "property",
        entity_id: Optional[str] = None,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
        status: str = "success",
    ):
        """Log audit trail entry"""
        audit_log = AuditLog(
            organization_id=as_uuid(organization_id),
            user_id=as_uuid(user_id) if user_id else None,
            action=action,
            entity_type=entity_type,
            entity_id=as_uuid(entity_id) if entity_id else None,
            old_values=old_values,
            new_values=new_values,
            status=status,
        )
        self.db.add(audit_log)
        self.db.commit()
