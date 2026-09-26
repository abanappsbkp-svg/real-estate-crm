"""
Real Estate CRM FastAPI Application
API-first architecture with modular services
"""

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
import logging
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool

import models
from config import settings

# ============================================================================
# Logging Configuration
# ============================================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Database Setup
# ============================================================================
DATABASE_URL = settings.DATABASE_URL
engine = create_engine(
    DATABASE_URL,
    echo=settings.DEBUG,
    poolclass=NullPool if settings.ENVIRONMENT == "testing" else None,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
try:
    models.Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Warning: Could not initialize database tables on startup: {e}")
def get_db():
    """Dependency injection for database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================================================
# Middleware: User Context
# ============================================================================
class UserContext:
    """Stores current user and org context"""
    def __init__(self):
        self.user_id: Optional[str] = None
        self.organization_id: Optional[str] = None
        self.user_role: Optional[str] = None
        self.preferred_language: str = "en"

# Using contextvars would be better for async, but storing in request state for simplicity
async def set_user_context(request: Request) -> UserContext:
    """Extract user context from JWT token"""
    # TODO: Implement JWT token validation
    context = UserContext()
    request.state.user_context = context
    return context

# ============================================================================
# Service Layer - Base Service
# ============================================================================
class BaseService:
    """Base service with common CRUD operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def audit_log(
        self,
        organization_id: str,
        user_id: Optional[str],
        action: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ):
        """Create an audit log entry"""
        audit_log = models.AuditLog(
            organization_id=uuid.UUID(organization_id),
            user_id=uuid.UUID(user_id) if user_id else None,
            action=action,
            entity_type=entity_type,
            entity_id=uuid.UUID(entity_id) if entity_id else None,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
            status="success",
        )
        self.db.add(audit_log)
        self.db.commit()

# ============================================================================
# Service Layer - Property Service
# ============================================================================
class PropertyService(BaseService):
    """Business logic for property management"""
    
    def create_property(
        self,
        organization_id: str,
        listing_agent_id: Optional[str],
        data: models.PropertyCreateSchema,
    ) -> models.Property:
        """Create a new property listing"""
        property_obj = models.Property(
            organization_id=uuid.UUID(organization_id),
            listing_agent_id=uuid.UUID(listing_agent_id) if listing_agent_id else None,
            type=data.type,
            status=data.status.value,
            mls_number=data.mls_number,
            address=data.address.dict(),
            square_feet=data.square_feet,
            lot_size=data.lot_size,
            bedrooms=data.bedrooms,
            bathrooms=data.bathrooms,
            year_built=data.year_built,
            list_price=data.list_price,
            currency=data.currency,
            rental_price=data.rental_price,
            description=data.description,
            features=data.features or {},
            custom_fields=data.custom_fields or {},
            tags=data.features and list(data.features.keys()) or [],
        )
        self.db.add(property_obj)
        self.db.commit()
        self.db.refresh(property_obj)
        
        # Audit log
        self.audit_log(
            organization_id=organization_id,
            user_id=listing_agent_id,
            action="property_created",
            entity_type="property",
            entity_id=str(property_obj.id),
            new_values=data.dict(),
        )
        
        return property_obj
    
    def update_property_status(
        self,
        property_id: str,
        new_status: models.PropertyStatus,
        reason: Optional[str] = None,
        changed_by: Optional[str] = None,
    ) -> models.Property:
        """Update property status and create audit trail"""
        property_obj = self.db.query(models.Property).filter(
            models.Property.id == uuid.UUID(property_id)
        ).first()
        
        if not property_obj:
            raise ValueError("Property not found")
        
        old_status = property_obj.status
        property_obj.status = new_status.value
        
        # Create history entry
        history = models.PropertyHistory(
            property_id=uuid.UUID(property_id),
            changed_by=uuid.UUID(changed_by) if changed_by else None,
            field_name="status",
            old_value=old_status,
            new_value=new_status.value,
            change_type="status_change",
            change_reason=reason,
        )
        self.db.add(history)
        self.db.commit()
        self.db.refresh(property_obj)
        
        return property_obj
    
    def update_price(
        self,
        property_id: str,
        new_price: float,
        reason: Optional[str] = None,
        changed_by: Optional[str] = None,
    ) -> models.Property:
        """Update property price and track history"""
        property_obj = self.db.query(models.Property).filter(
            models.Property.id == uuid.UUID(property_id)
        ).first()
        
        if not property_obj:
            raise ValueError("Property not found")
        
        old_price = float(property_obj.list_price)
        property_obj.list_price = new_price
        property_obj.add_price_history(new_price, reason)
        
        # Create history entry
        history = models.PropertyHistory(
            property_id=uuid.UUID(property_id),
            changed_by=uuid.UUID(changed_by) if changed_by else None,
            field_name="list_price",
            old_value=str(old_price),
            new_value=str(new_price),
            change_type="price_update",
            change_reason=reason,
        )
        self.db.add(history)
        self.db.commit()
        self.db.refresh(property_obj)
        
        return property_obj
    
    def get_property_details(self, property_id: str) -> models.Property:
        """Get full property details with all relationships"""
        return self.db.query(models.Property).filter(
            models.Property.id == uuid.UUID(property_id),
            models.Property.deleted_at.is_(None),
        ).first()
    
    def search_properties(
        self,
        organization_id: str,
        status: Optional[models.PropertyStatus] = None,
        type: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        bedrooms: Optional[int] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list, int]:
        """Search properties with filters"""
        query = self.db.query(models.Property).filter(
            models.Property.organization_id == uuid.UUID(organization_id),
            models.Property.deleted_at.is_(None),
        )
        
        if status:
            query = query.filter(models.Property.status == status.value)
        if type:
            query = query.filter(models.Property.type == type)
        if min_price:
            query = query.filter(models.Property.list_price >= min_price)
        if max_price:
            query = query.filter(models.Property.list_price <= max_price)
        if bedrooms:
            query = query.filter(models.Property.bedrooms == bedrooms)
        
        total = query.count()
        properties = query.offset(skip).limit(limit).all()
        
        return properties, total

# ============================================================================
# Service Layer - Client Service
# ============================================================================
class ClientService(BaseService):
    """Business logic for client and lead management"""
    
    def create_client(
        self,
        organization_id: str,
        data: models.ClientCreateSchema,
        assigned_agent_id: Optional[str] = None,
    ) -> models.Client:
        """Create a new client/lead"""
        client = models.Client(
            organization_id=uuid.UUID(organization_id),
            first_name=data.first_name,
            last_name=data.last_name,
            email=data.email,
            phone_primary=data.phone_primary,
            phone_secondary=data.phone_secondary,
            source=data.source.value,
            source_details=data.source_details,
            budget_min=data.budget_min,
            budget_max=data.budget_max,
            property_type_preferences=data.property_type_preferences or [],
            location_preferences=data.location_preferences or {},
            preferred_contact_method=data.preferred_contact_method,
            preferred_language=data.preferred_language,
            assigned_agent_id=uuid.UUID(assigned_agent_id) if assigned_agent_id else None,
        )
        self.db.add(client)
        self.db.commit()
        self.db.refresh(client)
        
        # Audit log
        self.audit_log(
            organization_id=organization_id,
            user_id=assigned_agent_id,
            action="client_created",
            entity_type="client",
            entity_id=str(client.id),
            new_values=data.dict(),
        )
        
        return client
    
    def log_interaction(
        self,
        client_id: str,
        organization_id: str,
        agent_id: str,
        interaction_type: models.InteractionType,
        subject: Optional[str] = None,
        content: Optional[str] = None,
        property_id: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> models.ClientInteraction:
        """Log a client interaction"""
        interaction = models.ClientInteraction(
            client_id=uuid.UUID(client_id),
            organization_id=uuid.UUID(organization_id),
            agent_id=uuid.UUID(agent_id),
            interaction_type=interaction_type.value,
            subject=subject,
            content=content,
            property_id=uuid.UUID(property_id) if property_id else None,
            duration_seconds=duration_seconds,
        )
        self.db.add(interaction)
        
        # Update client's last contacted date
        client = self.db.query(models.Client).filter(
            models.Client.id == uuid.UUID(client_id)
        ).first()
        if client:
            client.last_contacted = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(interaction)
        
        return interaction
    
    def find_matching_properties(
        self,
        client_id: str,
        limit: int = 10,
    ) -> list[models.PropertyMatch]:
        """Find properties matching client preferences"""
        client = self.db.query(models.Client).filter(
            models.Client.id == uuid.UUID(client_id)
        ).first()
        
        if not client:
            raise ValueError("Client not found")
        
        # Query properties matching client criteria
        query = self.db.query(models.Property).filter(
            models.Property.organization_id == client.organization_id,
            models.Property.status == models.PropertyStatus.AVAILABLE.value,
            models.Property.deleted_at.is_(None),
        )
        
        # Filter by type
        if client.property_type_preferences:
            query = query.filter(models.Property.type.in_(client.property_type_preferences))
        
        # Filter by price
        if client.budget_min:
            query = query.filter(models.Property.list_price >= client.budget_min)
        if client.budget_max:
            query = query.filter(models.Property.list_price <= client.budget_max)
        
        # Filter by bedrooms
        if client.bedroom_preferences:
            query = query.filter(models.Property.bedrooms == client.bedroom_preferences)
        
        properties = query.limit(limit).all()
        
        # Create or update matches
        matches = []
        for prop in properties:
            match_score = self._calculate_match_score(client, prop)
            
            existing_match = self.db.query(models.PropertyMatch).filter(
                models.PropertyMatch.client_id == uuid.UUID(client_id),
                models.PropertyMatch.property_id == prop.id,
            ).first()
            
            if existing_match:
                existing_match.match_score = match_score
                existing_match.updated_at = datetime.utcnow()
            else:
                existing_match = models.PropertyMatch(
                    client_id=uuid.UUID(client_id),
                    property_id=prop.id,
                    match_score=match_score,
                    match_reason=self._get_match_reasons(client, prop),
                )
                self.db.add(existing_match)
            
            matches.append(existing_match)
        
        self.db.commit()
        return matches
    
    def _calculate_match_score(self, client: models.Client, property: models.Property) -> float:
        """Calculate how well a property matches a client"""
        score = 0.0
        max_score = 100.0
        
        # Price match (max 30 points)
        if client.budget_min and client.budget_max:
            prop_price = float(property.list_price)
            budget_range = float(client.budget_max) - float(client.budget_min)
            if float(client.budget_min) <= prop_price <= float(client.budget_max):
                score += 30
            else:
                # Partial credit if close
                distance = min(
                    abs(prop_price - float(client.budget_min)),
                    abs(prop_price - float(client.budget_max)),
                )
                if distance < budget_range * 0.1:
                    score += 15
        
        # Type match (max 20 points)
        if client.property_type_preferences and property.type in client.property_type_preferences:
            score += 20
        
        # Bedrooms match (max 20 points)
        if client.bedroom_preferences and property.bedrooms == client.bedroom_preferences:
            score += 20
        elif client.bedroom_preferences and property.bedrooms:
            if abs(property.bedrooms - client.bedroom_preferences) <= 1:
                score += 10
        
        # Features match (max 30 points)
        if client.must_have_features and property.features:
            matching_features = len(
                set(client.must_have_features) & set(property.features.keys())
            )
            score += (matching_features / len(client.must_have_features)) * 30
        
        return min(score, max_score)
    
    def _get_match_reasons(self, client: models.Client, property: models.Property) -> Dict[str, Any]:
        """Generate reasons for a property match"""
        reasons = []
        
        if client.budget_min and client.budget_max:
            if float(client.budget_min) <= float(property.list_price) <= float(client.budget_max):
                reasons.append("price_match")
        
        if client.property_type_preferences and property.type in client.property_type_preferences:
            reasons.append("type_match")
        
        if client.bedroom_preferences and property.bedrooms == client.bedroom_preferences:
            reasons.append("bedroom_match")
        
        return {"reasons": reasons}

# ============================================================================
# Service Layer - Deal Service
# ============================================================================
class DealService(BaseService):
    """Business logic for deal pipeline management"""
    
    def create_deal(
        self,
        organization_id: str,
        agent_id: str,
        data: models.DealCreateSchema,
    ) -> models.Deal:
        """Create a new deal"""
        deal = models.Deal(
            organization_id=uuid.UUID(organization_id),
            client_id=uuid.UUID(data.client_id),
            property_id=uuid.UUID(data.property_id),
            agent_id=uuid.UUID(agent_id),
            deal_type=data.deal_type,
            stage=data.stage.value,
            proposed_price=data.proposed_price,
            commission_percent=data.commission_percent,
            internal_notes=data.internal_notes,
            expected_closing_date=data.expected_closing_date,
        )
        self.db.add(deal)
        self.db.commit()
        self.db.refresh(deal)
        
        # Create stage history entry
        stage_history = models.DealStageHistory(
            deal_id=deal.id,
            to_stage=data.stage.value,
            changed_by=uuid.UUID(agent_id),
        )
        self.db.add(stage_history)
        self.db.commit()
        
        # Audit log
        self.audit_log(
            organization_id=organization_id,
            user_id=agent_id,
            action="deal_created",
            entity_type="deal",
            entity_id=str(deal.id),
            new_values=data.dict(),
        )
        
        return deal
    
    def move_deal_stage(
        self,
        deal_id: str,
        new_stage: models.DealStage,
        changed_by: str,
        reason: Optional[str] = None,
    ) -> models.Deal:
        """Move deal to next stage"""
        deal = self.db.query(models.Deal).filter(
            models.Deal.id == uuid.UUID(deal_id)
        ).first()
        
        if not deal:
            raise ValueError("Deal not found")
        
        old_stage = deal.stage
        deal.stage = new_stage.value
        deal.updated_at = datetime.utcnow()
        
        # Create stage history
        stage_history = models.DealStageHistory(
            deal_id=deal.id,
            from_stage=old_stage,
            to_stage=new_stage.value,
            changed_by=uuid.UUID(changed_by),
            reason=reason,
        )
        self.db.add(stage_history)
        self.db.commit()
        self.db.refresh(deal)
        
        # Audit log
        self.audit_log(
            organization_id=str(deal.organization_id),
            user_id=changed_by,
            action="deal_stage_changed",
            entity_type="deal",
            entity_id=deal_id,
            old_values={"stage": old_stage},
            new_values={"stage": new_stage.value},
        )
        
        return deal
    
    def get_pipeline_stats(self, organization_id: str) -> Dict[str, Any]:
        """Get pipeline statistics"""
        deals = self.db.query(models.Deal).filter(
            models.Deal.organization_id == uuid.UUID(organization_id),
            models.Deal.is_active == True,
        ).all()
        
        stats = {
            "total_deals": len(deals),
            "by_stage": {},
            "total_value": 0,
            "close_rate": 0,
        }
        
        closed_deals = 0
        for deal in deals:
            if deal.stage not in stats["by_stage"]:
                stats["by_stage"][deal.stage] = 0
            stats["by_stage"][deal.stage] += 1
            
            if deal.proposed_price:
                stats["total_value"] += float(deal.proposed_price)
            
            if deal.stage == models.DealStage.CLOSED.value:
                closed_deals += 1
        
        if len(deals) > 0:
            stats["close_rate"] = (closed_deals / len(deals)) * 100
        
        return stats

# ============================================================================
# Service Layer - Call Log Service
# ============================================================================
class CallLogService(BaseService):
    """Business logic for call logging and analysis"""
    
    def create_call_log(
        self,
        organization_id: str,
        agent_id: str,
        call_type: models.CallType,
        client_id: Optional[str] = None,
        property_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        duration_seconds: int = 0,
        transcript: Optional[str] = None,
        recording_url: Optional[str] = None,
    ) -> models.CallLog:
        """Create a call log entry"""
        call_log = models.CallLog(
            organization_id=uuid.UUID(organization_id),
            client_id=uuid.UUID(client_id) if client_id else None,
            property_id=uuid.UUID(property_id) if property_id else None,
            agent_id=uuid.UUID(agent_id),
            call_type=call_type.value,
            phone_number=phone_number,
            duration_seconds=duration_seconds,
            transcript=transcript,
            recording_url=recording_url,
        )
        
        self.db.add(call_log)
        self.db.commit()
        self.db.refresh(call_log)
        
        # Optionally trigger AI processing for transcript/summary
        # TODO: Queue async job for transcript processing
        
        return call_log

# ============================================================================
# FastAPI Application Factory
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    logger.info("🚀 Real Estate CRM API starting...")
    yield
    logger.info("🛑 Real Estate CRM API shutting down...")

def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    
    app = FastAPI(
        title="Real Estate CRM API",
        description="Comprehensive CRM system for property sales and rentals",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # ========================================================================
    # Middleware
    # ========================================================================
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Trusted Host
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS,
    )
    
    # Custom error handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler with logging"""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )
    
    # ========================================================================
    # Health Check
    # ========================================================================
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint"""
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
    
    # ========================================================================
    # Authentication Middleware
    # ========================================================================
    # from middleware_auth import attach_user_context  # TODO: Fix HTTPCredentials import
    
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
    # return await attach_user_context(request, call_next)  # TODO: Fix HTTPCredentials import
    return await call_next(request)
    # ========================================================================
    # API Routes
    # ========================================================================
    
    # Authentication routes
    import routers_auth
    app.include_router(routers_auth.router, prefix="/api/v1")
    logger.info("✅ Authentication routes loaded")
    
    # Properties routes
    try:
        import routers_properties
        app.include_router(routers_properties.router, prefix="/api/v1")
        logger.info("✅ Properties routes loaded")
    except ImportError as e:
        logger.warning(f"⚠️ Properties routes unavailable: {e}")
    
    # Clients routes
    try:
        import routers_clients
        app.include_router(routers_clients.router, prefix="/api/v1")
        logger.info("✅ Clients routes loaded")
    except ImportError as e:
        logger.warning(f"⚠️ Clients routes unavailable: {e}")
    
    # Deals routes
    try:
        import routers_deals
        app.include_router(routers_deals.router, prefix="/api/v1")
        logger.info("✅ Deals routes loaded")
    except ImportError as e:
        logger.warning(f"⚠️ Deals routes unavailable: {e}")
    
    # Call Logs routes (Phase 5)
    try:
        import routers_calls
        app.include_router(routers_calls.router, prefix="/api/v1")
        logger.info("✅ Call Logging routes loaded")
    except ImportError as e:
        logger.warning(f"⚠️ Call Logging routes unavailable: {e}")
    
    # Document Management routes (Phase 5 continued)
    try:
        import routers_documents
        app.include_router(routers_documents.router, prefix="/api/v1")
        logger.info("✅ Document Management routes loaded")
    except ImportError as e:
        logger.warning(f"⚠️ Document Management routes unavailable: {e}")
    
    # TODO: Import other routers as they're created
    # Notifications, Advanced Reporting coming in Phase 5-6
    
    return app

# ============================================================================
# Create app instance
# ============================================================================
app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=settings.DEBUG)
