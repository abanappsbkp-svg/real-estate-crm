"""
Clients Service
Business logic for client management, preferences, interactions, and matching
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
import uuid
from models import as_uuid

from models import (
    Client, ClientInteraction, InteractionType, PropertyMatch,
    Property, User, UserRole, AuditLog, Organization
)

class ClientService:
    """Service for client management and operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ========================================================================
    # Create & Register Clients
    # ========================================================================
    
    def create_client(
        self,
        organization_id: str,
        created_by_id: str,
        email: str,
        first_name: str,
        last_name: str,
        phone: Optional[str] = None,
        client_type: str = "buyer",  # buyer, seller, both
        status: str = "active",  # active, inactive, archived
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        property_type_preferences: Optional[List[str]] = None,
        bedroom_preferences: Optional[int] = None,
        location_preferences: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> Client:
        """
        Create a new client profile
        
        Args:
            organization_id: Organization UUID
            created_by_id: Agent creating the client
            email: Client email
            first_name: First name
            last_name: Last name
            phone: Phone number
            client_type: buyer, seller, or both
            status: active, inactive, or archived
            budget_min: Minimum budget (for buyers)
            budget_max: Maximum budget (for buyers)
            property_type_preferences: List of preferred property types
            bedroom_preferences: Preferred number of bedrooms
            location_preferences: Dict with city, state, zip preferences
            notes: Internal notes about client
            custom_fields: Additional custom data
        
        Returns:
            Created Client object
        """
        client = Client(
            organization_id=as_uuid(organization_id),
            created_by_id=as_uuid(created_by_id),
            email=email.lower(),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            type=client_type,
            status=status,
            budget_min=budget_min,
            budget_max=budget_max,
            property_type_preferences=property_type_preferences or [],
            bedroom_preferences=bedroom_preferences,
            location_preferences=location_preferences or {},
            notes=notes,
            custom_fields=custom_fields or {},
        )
        
        self.db.add(client)
        self.db.commit()
        self.db.refresh(client)
        
        # Log creation
        self._log_audit(
            organization_id=organization_id,
            user_id=created_by_id,
            action="client_created",
            entity_type="client",
            entity_id=str(client.id),
            new_values={
                "email": email,
                "type": client_type,
                "budget": {"min": budget_min, "max": budget_max},
            },
        )
        
        return client
    
    # ========================================================================
    # Read & Retrieve Clients
    # ========================================================================
    
    def get_client(
        self,
        client_id: str,
        organization_id: Optional[str] = None
    ) -> Optional[Client]:
        """Get client by ID"""
        query = self.db.query(Client).filter(
            Client.id == as_uuid(client_id),
            Client.deleted_at.is_(None),
        )
        
        if organization_id:
            query = query.filter(Client.organization_id == as_uuid(organization_id))
        
        return query.first()
    
    def list_clients(
        self,
        organization_id: str,
        skip: int = 0,
        limit: int = 50,
        client_type: Optional[str] = None,
        status: Optional[str] = None,
        created_by_id: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[List[Client], int]:
        """
        List clients with filters
        
        Args:
            organization_id: Organization UUID
            skip: Number to skip
            limit: Number to return
            client_type: buyer, seller, both
            status: active, inactive, archived
            created_by_id: Filter by agent who created
            search_query: Search by name or email
            sort_by: created_at, name, last_interaction
            sort_order: asc or desc
        
        Returns:
            Tuple of (clients list, total count)
        """
        query = self.db.query(Client).filter(
            Client.organization_id == as_uuid(organization_id),
            Client.deleted_at.is_(None),
        )
        
        # Apply filters
        if client_type:
            query = query.filter(Client.type == client_type)
        
        if status:
            query = query.filter(Client.status == status)
        
        if created_by_id:
            query = query.filter(Client.created_by_id == as_uuid(created_by_id))
        
        if search_query:
            search_term = f"%{search_query}%"
            query = query.filter(
                or_(
                    func.lower(Client.first_name).ilike(search_term),
                    func.lower(Client.last_name).ilike(search_term),
                    func.lower(Client.email).ilike(search_term),
                )
            )
        
        # Count total
        total = query.count()
        
        # Sort
        if sort_by == "name":
            query = query.order_by(
                Client.first_name.desc() if sort_order == "desc" else Client.first_name.asc()
            )
        elif sort_by == "last_interaction":
            query = query.order_by(
                Client.last_interaction_at.desc() if sort_order == "desc" else Client.last_interaction_at.asc()
            )
        else:  # created_at
            query = query.order_by(
                Client.created_at.desc() if sort_order == "desc" else Client.created_at.asc()
            )
        
        # Pagination
        clients = query.offset(skip).limit(limit).all()
        
        return clients, total
    
    # ========================================================================
    # Update Client
    # ========================================================================
    
    def update_client(
        self,
        client_id: str,
        organization_id: str,
        **kwargs
    ) -> Client:
        """
        Update client information
        
        Args:
            client_id: Client UUID
            organization_id: Organization UUID
            **kwargs: Fields to update
        
        Returns:
            Updated Client object
        """
        client = self.get_client(client_id, organization_id)
        
        if not client:
            raise ValueError("Client not found")
        
        old_values = {}
        new_values = {}
        
        # Allowed fields
        allowed_fields = {
            'first_name', 'last_name', 'phone', 'email', 'type',
            'status', 'budget_min', 'budget_max', 
            'property_type_preferences', 'bedroom_preferences',
            'location_preferences', 'notes', 'custom_fields'
        }
        
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                old_values[field] = getattr(client, field)
                setattr(client, field, value)
                new_values[field] = value
        
        client.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(client)
        
        # Log update
        if new_values:
            self._log_audit(
                organization_id=organization_id,
                user_id=None,
                action="client_updated",
                entity_type="client",
                entity_id=client_id,
                old_values=old_values,
                new_values=new_values,
            )
        
        return client
    
    # ========================================================================
    # Client Interactions
    # ========================================================================
    
    def log_interaction(
        self,
        client_id: str,
        organization_id: str,
        user_id: str,
        interaction_type: str,  # call, email, meeting, showing, offer
        description: Optional[str] = None,
        property_id: Optional[str] = None,
        notes: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        follow_up_date: Optional[datetime] = None,
    ) -> ClientInteraction:
        """
        Log a client interaction (call, email, meeting, etc.)
        
        Args:
            client_id: Client UUID
            organization_id: Organization UUID
            user_id: User logging the interaction
            interaction_type: Type of interaction
            description: What was discussed
            property_id: Property related to interaction (optional)
            notes: Additional notes
            duration_minutes: Duration in minutes (for calls/meetings)
            follow_up_date: When to follow up
        
        Returns:
            Created ClientInteraction object
        """
        interaction = ClientInteraction(
            client_id=as_uuid(client_id),
            organization_id=as_uuid(organization_id),
            user_id=as_uuid(user_id),
            type=interaction_type,
            description=description,
            property_id=as_uuid(property_id) if property_id else None,
            notes=notes,
            duration_minutes=duration_minutes,
            follow_up_date=follow_up_date,
        )
        
        self.db.add(interaction)
        
        # Update client's last interaction time
        client = self.get_client(client_id, organization_id)
        if client:
            client.last_interaction_at = datetime.utcnow()
            client.interaction_count = (client.interaction_count or 0) + 1
        
        self.db.commit()
        self.db.refresh(interaction)
        
        # Log interaction
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="client_interaction_logged",
            entity_type="client",
            entity_id=client_id,
            new_values={
                "interaction_type": interaction_type,
                "property_id": property_id,
            },
        )
        
        return interaction
    
    def get_client_interactions(
        self,
        client_id: str,
        limit: int = 50,
        interaction_type: Optional[str] = None,
    ) -> List[ClientInteraction]:
        """Get client's interaction history"""
        query = self.db.query(ClientInteraction).filter(
            ClientInteraction.client_id == as_uuid(client_id)
        )
        
        if interaction_type:
            query = query.filter(ClientInteraction.type == interaction_type)
        
        return query.order_by(
            ClientInteraction.created_at.desc()
        ).limit(limit).all()
    
    def get_pending_follow_ups(
        self,
        organization_id: str,
        user_id: Optional[str] = None,
    ) -> List[ClientInteraction]:
        """Get pending follow-ups"""
        query = self.db.query(ClientInteraction).filter(
            ClientInteraction.follow_up_date.isnot(None),
            ClientInteraction.follow_up_date <= datetime.utcnow(),
            ClientInteraction.completed_at.is_(None),
        )
        
        if user_id:
            query = query.filter(ClientInteraction.user_id == as_uuid(user_id))
        
        return query.order_by(ClientInteraction.follow_up_date.asc()).all()
    
    # ========================================================================
    # Client Preferences & Matching
    # ========================================================================
    
    def update_preferences(
        self,
        client_id: str,
        organization_id: str,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        property_types: Optional[List[str]] = None,
        bedrooms: Optional[int] = None,
        bathrooms: Optional[float] = None,
        location_preferences: Optional[Dict[str, Any]] = None,
    ) -> Client:
        """Update client's property preferences"""
        client = self.get_client(client_id, organization_id)
        
        if not client:
            raise ValueError("Client not found")
        
        if budget_min is not None:
            client.budget_min = budget_min
        if budget_max is not None:
            client.budget_max = budget_max
        if property_types is not None:
            client.property_type_preferences = property_types
        if bedrooms is not None:
            client.bedroom_preferences = bedrooms
        if location_preferences is not None:
            client.location_preferences = location_preferences
        
        client.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(client)
        
        return client
    
    def find_matching_properties(
        self,
        client_id: str,
        organization_id: str,
        limit: int = 20,
    ) -> List[PropertyMatch]:
        """
        Find properties matching client preferences
        
        Uses rule-based matching:
        - Price match (if budget set)
        - Property type match
        - Location match (city/state preferences)
        - Bedroom match
        - Status (available only)
        """
        client = self.get_client(client_id, organization_id)
        
        if not client:
            raise ValueError("Client not found")
        
        # Build query for matching properties
        query = self.db.query(Property).filter(
            Property.organization_id == as_uuid(organization_id),
            Property.status == "available",
            Property.deleted_at.is_(None),
        )
        
        # Filter by type
        if client.property_type_preferences:
            query = query.filter(Property.type.in_(client.property_type_preferences))
        
        # Filter by price
        if client.budget_min:
            query = query.filter(Property.list_price >= client.budget_min)
        if client.budget_max:
            query = query.filter(Property.list_price <= client.budget_max)
        
        # Filter by bedrooms
        if client.bedroom_preferences:
            query = query.filter(Property.bedrooms >= client.bedroom_preferences)
        
        # Filter by location if preferences set
        if client.location_preferences:
            if "cities" in client.location_preferences:
                cities = client.location_preferences["cities"]
                query = query.filter(
                    func.lower(Property.address["city"].astext).in_(
                        [c.lower() for c in cities]
                    )
                )
            if "states" in client.location_preferences:
                states = client.location_preferences["states"]
                query = query.filter(
                    func.lower(Property.address["state"].astext).in_(
                        [s.lower() for s in states]
                    )
                )
        
        properties = query.limit(limit).all()
        
        # Create or update matches
        matches = []
        for prop in properties:
            match_score = self._calculate_match_score(client, prop)
            
            existing_match = self.db.query(PropertyMatch).filter(
                PropertyMatch.client_id == as_uuid(client_id),
                PropertyMatch.property_id == prop.id,
            ).first()
            
            if existing_match:
                existing_match.match_score = match_score
                existing_match.updated_at = datetime.utcnow()
            else:
                existing_match = PropertyMatch(
                    client_id=as_uuid(client_id),
                    property_id=prop.id,
                    match_score=match_score,
                    match_reason=self._get_match_reasons(client, prop),
                )
                self.db.add(existing_match)
            
            matches.append(existing_match)
        
        self.db.commit()
        return matches
    
    def _calculate_match_score(self, client: Client, property: Property) -> float:
        """Calculate match score between client and property (0-100)"""
        score = 0.0
        
        # Price match (max 30 points)
        if client.budget_min and client.budget_max:
            prop_price = float(property.list_price)
            if client.budget_min <= prop_price <= client.budget_max:
                score += 30
            else:
                # Partial credit if close
                budget_range = float(client.budget_max) - float(client.budget_min)
                distance_pct = abs(prop_price - (float(client.budget_min) + float(client.budget_max)) / 2) / budget_range * 100
                score += max(0, 30 - (distance_pct / 2))
        
        # Type match (max 25 points)
        if client.property_type_preferences:
            if property.type in client.property_type_preferences:
                score += 25
        else:
            score += 10  # Some points if no preference
        
        # Bedroom match (max 20 points)
        if client.bedroom_preferences:
            if property.bedrooms == client.bedroom_preferences:
                score += 20
            elif property.bedrooms and property.bedrooms >= client.bedroom_preferences:
                score += 15  # Partial credit for more bedrooms
        else:
            score += 5
        
        # Location match (max 25 points)
        if client.location_preferences:
            match = False
            if "cities" in client.location_preferences:
                if property.address.get("city", "").lower() in [c.lower() for c in client.location_preferences["cities"]]:
                    match = True
            if "states" in client.location_preferences:
                if property.address.get("state", "").lower() in [s.lower() for s in client.location_preferences["states"]]:
                    match = True
            
            if match:
                score += 25
        else:
            score += 5
        
        return min(100.0, score)
    
    def _get_match_reasons(self, client: Client, property: Property) -> List[str]:
        """Get human-readable reasons why property matches client"""
        reasons = []
        
        # Price reason
        if client.budget_min and client.budget_max:
            if client.budget_min <= property.list_price <= client.budget_max:
                reasons.append(f"Price ${property.list_price:,.0f} within budget")
        
        # Type reason
        if client.property_type_preferences and property.type in client.property_type_preferences:
            reasons.append(f"Matches preferred type: {property.type}")
        
        # Bedroom reason
        if client.bedroom_preferences and property.bedrooms:
            if property.bedrooms == client.bedroom_preferences:
                reasons.append(f"Exact match: {property.bedrooms} bedrooms")
            elif property.bedrooms > client.bedroom_preferences:
                reasons.append(f"Has {property.bedrooms} bedrooms (wants {client.bedroom_preferences}+)")
        
        # Location reason
        if client.location_preferences:
            location_str = f"{property.address.get('city', '')}, {property.address.get('state', '')}"
            reasons.append(f"Located in {location_str}")
        
        return reasons if reasons else ["General match based on available criteria"]
    
    # ========================================================================
    # Delete & Archive
    # ========================================================================
    
    def archive_client(
        self,
        client_id: str,
        organization_id: str,
        user_id: str,
        reason: Optional[str] = None,
    ) -> Client:
        """Archive client (soft delete)"""
        client = self.get_client(client_id, organization_id)
        
        if not client:
            raise ValueError("Client not found")
        
        client.status = "archived"
        client.deleted_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(client)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="client_archived",
            entity_type="client",
            entity_id=client_id,
            new_values={"reason": reason or "no reason provided"},
        )
        
        return client
    
    def restore_client(self, client_id: str, organization_id: str) -> Client:
        """Restore archived client"""
        client = self.db.query(Client).filter(
            Client.id == as_uuid(client_id),
            Client.organization_id == as_uuid(organization_id),
        ).first()
        
        if not client:
            raise ValueError("Client not found")
        
        client.deleted_at = None
        client.status = "active"
        self.db.commit()
        self.db.refresh(client)
        
        return client
    
    # ========================================================================
    # Statistics
    # ========================================================================
    
    def get_client_stats(self, organization_id: str) -> Dict[str, Any]:
        """Get client statistics for organization"""
        total = self.db.query(Client).filter(
            Client.organization_id == as_uuid(organization_id),
            Client.deleted_at.is_(None),
        ).count()
        
        buyers = self.db.query(Client).filter(
            Client.organization_id == as_uuid(organization_id),
            Client.type.in_(["buyer", "both"]),
            Client.deleted_at.is_(None),
        ).count()
        
        sellers = self.db.query(Client).filter(
            Client.organization_id == as_uuid(organization_id),
            Client.type.in_(["seller", "both"]),
            Client.deleted_at.is_(None),
        ).count()
        
        active = self.db.query(Client).filter(
            Client.organization_id == as_uuid(organization_id),
            Client.status == "active",
            Client.deleted_at.is_(None),
        ).count()
        
        # Clients with interactions in last 30 days
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        active_recently = self.db.query(Client).filter(
            Client.organization_id == as_uuid(organization_id),
            Client.last_interaction_at >= thirty_days_ago,
            Client.deleted_at.is_(None),
        ).count()
        
        return {
            "total_clients": total,
            "buyers": buyers,
            "sellers": sellers,
            "active": active,
            "active_recently": active_recently,
            "percentage_buyers": (buyers / total * 100) if total > 0 else 0,
            "percentage_sellers": (sellers / total * 100) if total > 0 else 0,
            "percentage_active": (active / total * 100) if total > 0 else 0,
        }
    
    # ========================================================================
    # Private Methods
    # ========================================================================
    
    def _log_audit(
        self,
        organization_id: str,
        user_id: Optional[str],
        action: str,
        entity_type: str = "client",
        entity_id: Optional[str] = None,
        old_values: Optional[dict] = None,
        new_values: Optional[dict] = None,
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
        )
        self.db.add(audit_log)
        self.db.commit()
