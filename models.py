"""
Core Models for Real Estate CRM
SQLAlchemy ORM models + Pydantic schemas for validation
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
import uuid

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, TIMESTAMP,
    ForeignKey, ARRAY, JSON, LargeBinary, Numeric, Text, Index,
    UniqueConstraint, CheckConstraint, ForeignKeyConstraint,
    func, and_, or_
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import text

from pydantic import BaseModel, EmailStr, Field, validator, root_validator
from pydantic.json import pydantic_encoder

# ============================================================================
# Enums (mirror database enums)
# ============================================================================
class UserRole(str, Enum):
    ADMIN = "admin"
    AGENT = "agent"
    VIEWER = "viewer"

class PropertyStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    RENTED = "rented"
    DELISTED = "delisted"

class DealStage(str, Enum):
    INQUIRY = "inquiry"
    SHOWING = "showing"
    OFFER = "offer"
    NEGOTIATION = "negotiation"
    CONTINGENT = "contingent"
    CLOSING = "closing"
    CLOSED = "closed"
    LOST = "lost"

class LeadSource(str, Enum):
    WEBSITE = "website"
    REFERRAL = "referral"
    COLD_CALL = "cold_call"
    EMAIL = "email"
    SOCIAL_MEDIA = "social_media"
    WALK_IN = "walk_in"
    OTHER = "other"

class CallType(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    CALLBACK = "callback"

class InteractionType(str, Enum):
    CALL = "call"
    EMAIL = "email"
    SMS = "sms"
    SHOWING = "showing"
    NOTE = "note"

# ============================================================================
# SQLAlchemy Base
# ============================================================================
Base = declarative_base()

# ============================================================================
# Organization & Users (SQLAlchemy Models)
# ============================================================================
class Language(Base):
    """Supported languages in the system"""
    __tablename__ = "languages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(5), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    translations = relationship("Translation", back_populates="language")

class Organization(Base):
    """Multi-tenant organizations"""
    __tablename__ = "organizations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    logo_url = Column(String)
    website = Column(String(255))
    phone = Column(String(20))
    address = Column(JSONB, default={})
    settings = Column(JSONB, default={"default_language": "en", "currency": "USD", "timezone": "UTC"})
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    properties = relationship("Property", back_populates="organization", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="organization", cascade="all, delete-orphan")
    deals = relationship("Deal", back_populates="organization", cascade="all, delete-orphan")
    translations = relationship("Translation", back_populates="organization", cascade="all, delete-orphan")
    call_logs = relationship("CallLog", back_populates="organization", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="organization", cascade="all, delete-orphan")

class User(Base):
    """System users with role-based access"""
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_org_email"),
        Index("idx_users_org_role", "organization_id", "role"),
        Index("idx_users_email", "email"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(20))
    role = Column(String(20), default=UserRole.VIEWER.value, nullable=False)
    avatar_url = Column(String)
    preferred_language = Column(String(5), default="en", ForeignKey("languages.code"))
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime)
    email_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    organization = relationship("Organization", back_populates="users")
    language = relationship("Language")
    assigned_clients = relationship("Client", foreign_keys="Client.assigned_agent_id", back_populates="assigned_agent")
    created_properties = relationship("Property", foreign_keys="Property.listing_agent_id", back_populates="listing_agent")
    deals = relationship("Deal", back_populates="agent")
    interactions = relationship("ClientInteraction", back_populates="agent")
    call_logs = relationship("CallLog", back_populates="agent")
    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
    
    @validates("email")
    def validate_email(self, key, email):
        return email.lower()

# ============================================================================
# Properties (SQLAlchemy Models)
# ============================================================================
class Property(Base):
    """Property listings"""
    __tablename__ = "properties"
    __table_args__ = (
        Index("idx_properties_org_status", "organization_id", "status"),
        Index("idx_properties_agent", "listing_agent_id"),
        Index("idx_properties_mls", "mls_number"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    listing_agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    
    # Basic info
    type = Column(String(50), nullable=False)  # apartment, house, commercial, land
    status = Column(String(50), default=PropertyStatus.AVAILABLE.value, nullable=False)
    mls_number = Column(String(100))
    
    # Location & details
    address = Column(JSONB, nullable=False)
    square_feet = Column(Numeric(10, 2))
    lot_size = Column(Numeric(10, 2))
    bedrooms = Column(Integer)
    bathrooms = Column(Numeric(4, 2))
    year_built = Column(Integer)
    features = Column(JSONB, default={})
    
    # Pricing
    list_price = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD")
    rental_price = Column(Numeric(12, 2))
    price_history = Column(JSONB, default=[])
    
    # Media
    primary_photo_url = Column(String)
    photo_urls = Column(ARRAY(String), default=[])
    video_url = Column(String)
    virtual_tour_url = Column(String)
    
    # Metadata
    description = Column(Text)
    tags = Column(ARRAY(String), default=[])
    custom_fields = Column(JSONB, default={})
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime)
    
    # Relationships
    organization = relationship("Organization", back_populates="properties")
    listing_agent = relationship("User", foreign_keys=[listing_agent_id], back_populates="created_properties")
    history = relationship("PropertyHistory", back_populates="property", cascade="all, delete-orphan")
    deals = relationship("Deal", back_populates="property")
    matches = relationship("PropertyMatch", back_populates="property", cascade="all, delete-orphan")
    showings = relationship("Showing", back_populates="property", cascade="all, delete-orphan")
    interactions = relationship("ClientInteraction", back_populates="property")
    call_logs = relationship("CallLog", back_populates="property")
    
    def is_active(self) -> bool:
        return self.deleted_at is None and self.status != PropertyStatus.DELISTED.value
    
    def add_price_history(self, new_price: Decimal, reason: str = None):
        """Track price changes"""
        if not self.price_history:
            self.price_history = []
        self.price_history.append({
            "price": float(new_price),
            "date": datetime.utcnow().isoformat(),
            "reason": reason
        })

class PropertyHistory(Base):
    """Audit trail for property changes"""
    __tablename__ = "property_history"
    __table_args__ = (
        Index("idx_property_history_property", "property_id"),
        Index("idx_property_history_date", "created_at"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    field_name = Column(String(100))
    old_value = Column(Text)
    new_value = Column(Text)
    change_type = Column(String(50))
    change_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    property = relationship("Property", back_populates="history")
    changed_by_user = relationship("User")

# ============================================================================
# Clients & Leads
# ============================================================================
class Client(Base):
    """Leads and clients"""
    __tablename__ = "clients"
    __table_args__ = (
        Index("idx_clients_org", "organization_id"),
        Index("idx_clients_agent", "assigned_agent_id"),
        Index("idx_clients_email", "email"),
        Index("idx_clients_phone", "phone_primary"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    
    # Personal info
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255))
    phone_primary = Column(String(20))
    phone_secondary = Column(String(20))
    date_of_birth = Column(date)
    
    # Lead info
    source = Column(String(50), nullable=False)
    source_details = Column(Text)
    acquisition_date = Column(DateTime, default=datetime.utcnow)
    
    # Preferences
    preferred_contact_method = Column(String(50))  # email, phone, sms
    preferred_language = Column(String(5), default="en")
    do_not_contact = Column(Boolean, default=False)
    do_not_call = Column(Boolean, default=False)
    
    # Financial
    budget_min = Column(Numeric(12, 2))
    budget_max = Column(Numeric(12, 2))
    financial_preapproval_url = Column(String)
    
    # Search preferences
    property_type_preferences = Column(ARRAY(String), default=[])
    location_preferences = Column(JSONB, default={})
    bedroom_preferences = Column(Integer)
    bathroom_preferences = Column(Numeric(4, 2))
    must_have_features = Column(ARRAY(String), default=[])
    
    # Status
    is_active = Column(Boolean, default=True)
    assigned_agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    last_contacted = Column(DateTime)
    
    # Custom fields
    custom_fields = Column(JSONB, default={})
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime)
    
    # Relationships
    organization = relationship("Organization", back_populates="clients")
    assigned_agent = relationship("User", foreign_keys=[assigned_agent_id], back_populates="assigned_clients")
    interactions = relationship("ClientInteraction", back_populates="client", cascade="all, delete-orphan")
    deals = relationship("Deal", back_populates="client")
    matches = relationship("PropertyMatch", back_populates="client", cascade="all, delete-orphan")
    showings = relationship("Showing", back_populates="client", cascade="all, delete-orphan")
    call_logs = relationship("CallLog", back_populates="client")
    
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
    
    @property
    def days_since_contact(self) -> Optional[int]:
        if not self.last_contacted:
            return None
        return (datetime.utcnow() - self.last_contacted).days
    
    def matches_criteria(self, property: Property) -> bool:
        """Check if property matches client preferences"""
        if self.property_type_preferences and property.type not in self.property_type_preferences:
            return False
        
        if self.budget_min and Decimal(str(property.list_price)) < self.budget_min:
            return False
        
        if self.budget_max and Decimal(str(property.list_price)) > self.budget_max:
            return False
        
        if self.bedroom_preferences and property.bedrooms != self.bedroom_preferences:
            return False
        
        return True

class ClientInteraction(Base):
    """Contact history with clients"""
    __tablename__ = "client_interactions"
    __table_args__ = (
        Index("idx_interactions_client", "client_id"),
        Index("idx_interactions_agent", "agent_id"),
        Index("idx_interactions_property", "property_id"),
        Index("idx_interactions_date", "created_at"),
        Index("idx_interactions_type", "interaction_type"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    
    interaction_type = Column(String(50), nullable=False)
    direction = Column(String(20))  # inbound, outbound
    subject = Column(String(255))
    content = Column(Text)
    duration_seconds = Column(Integer)
    
    # Call logging
    call_transcript = Column(Text)
    call_summary = Column(Text)
    call_recording_url = Column(String)
    call_sentiment = Column(String(50))
    
    # Property reference
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"))
    
    # Status
    follow_up_required = Column(Boolean, default=False)
    follow_up_date = Column(DateTime)
    next_step = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    client = relationship("Client", back_populates="interactions")
    organization = relationship("Organization")
    agent = relationship("User", back_populates="interactions")
    property = relationship("Property", back_populates="interactions")

# ============================================================================
# Deal Pipeline
# ============================================================================
class Deal(Base):
    """Sales and rental deals"""
    __tablename__ = "deals"
    __table_args__ = (
        Index("idx_deals_org", "organization_id"),
        Index("idx_deals_client", "client_id"),
        Index("idx_deals_property", "property_id"),
        Index("idx_deals_agent", "agent_id"),
        Index("idx_deals_stage", "stage"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    
    # Deal info
    deal_type = Column(String(50), nullable=False)  # sale, rental
    stage = Column(String(50), default=DealStage.INQUIRY.value, nullable=False)
    
    # Financial
    proposed_price = Column(Numeric(12, 2))
    agreed_price = Column(Numeric(12, 2))
    commission_percent = Column(Numeric(5, 2))
    commission_amount = Column(Numeric(12, 2))
    closing_cost = Column(Numeric(12, 2))
    
    # Timeline
    inquiry_date = Column(DateTime, default=datetime.utcnow)
    first_showing_date = Column(DateTime)
    offer_date = Column(DateTime)
    expected_closing_date = Column(DateTime)
    actual_closing_date = Column(DateTime)
    
    # Notes
    internal_notes = Column(Text)
    client_notes = Column(Text)
    contingencies = Column(Text)
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Audit
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime)
    
    # Relationships
    organization = relationship("Organization", back_populates="deals")
    client = relationship("Client", back_populates="deals")
    property = relationship("Property", back_populates="deals")
    agent = relationship("User", back_populates="deals")
    stage_history = relationship("DealStageHistory", back_populates="deal", cascade="all, delete-orphan")
    
    @property
    def is_open(self) -> bool:
        return self.is_active and self.stage not in [DealStage.CLOSED.value, DealStage.LOST.value]

class DealStageHistory(Base):
    """Audit trail for deal stage changes"""
    __tablename__ = "deal_stage_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deal_id = Column(UUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    from_stage = Column(String(50))
    to_stage = Column(String(50), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    deal = relationship("Deal", back_populates="stage_history")
    changed_by_user = relationship("User")

# ============================================================================
# Property Showings
# ============================================================================
class Showing(Base):
    """Scheduled property showings"""
    __tablename__ = "showings"
    __table_args__ = (
        Index("idx_showings_property", "property_id"),
        Index("idx_showings_client", "client_id"),
        Index("idx_showings_agent", "agent_id"),
        Index("idx_showings_time", "scheduled_time"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    
    scheduled_time = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=60)
    status = Column(String(50), nullable=False)  # scheduled, completed, cancelled, no_show
    
    feedback = Column(Text)
    client_interest_level = Column(Integer)  # 1-5
    follow_up_needed = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    property = relationship("Property", back_populates="showings")
    client = relationship("Client", back_populates="showings")
    agent = relationship("User")

# ============================================================================
# Property Matching
# ============================================================================
class PropertyMatch(Base):
    """Cached property-client matches"""
    __tablename__ = "property_matches"
    __table_args__ = (
        UniqueConstraint("client_id", "property_id", name="uq_client_property"),
        Index("idx_property_matches_client", "client_id"),
        Index("idx_property_matches_score", "match_score"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    
    match_score = Column(Numeric(5, 2))
    match_reason = Column(JSONB, default={})
    viewed_at = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    client = relationship("Client", back_populates="matches")
    property = relationship("Property", back_populates="matches")

# ============================================================================
# Call Logs
# ============================================================================
class CallLog(Base):
    """Detailed call logging and analysis"""
    __tablename__ = "call_logs"
    __table_args__ = (
        Index("idx_call_logs_org", "organization_id"),
        Index("idx_call_logs_client", "client_id"),
        Index("idx_call_logs_agent", "agent_id"),
        Index("idx_call_logs_date", "created_at"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"))
    property_id = Column(UUID(as_uuid=True), ForeignKey("properties.id", ondelete="SET NULL"))
    agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False)
    
    call_type = Column(String(50), nullable=False)
    phone_number = Column(String(20))
    duration_seconds = Column(Integer, nullable=False)
    
    transcript = Column(Text)
    transcript_language = Column(String(5))
    ai_summary = Column(Text)
    key_topics = Column(ARRAY(String), default=[])
    action_items = Column(ARRAY(String), default=[])
    
    recording_url = Column(String)
    recording_duration_seconds = Column(Integer)
    
    sentiment_score = Column(Numeric(3, 2))
    sentiment_label = Column(String(50))
    
    call_quality = Column(String(50))
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime)
    
    # Relationships
    organization = relationship("Organization", back_populates="call_logs")
    client = relationship("Client", back_populates="call_logs")
    property = relationship("Property", back_populates="call_logs")
    agent = relationship("User", back_populates="call_logs")

# ============================================================================
# Multilingual Support
# ============================================================================
class Translation(Base):
    """Multilingual content storage"""
    __tablename__ = "translations"
    __table_args__ = (
        UniqueConstraint("organization_id", "language_id", "entity_type", "entity_id", "key",
                        name="uq_translation"),
        Index("idx_translations_entity", "entity_type", "entity_id"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    language_id = Column(UUID(as_uuid=True), ForeignKey("languages.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    key = Column(String(255))
    value = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    organization = relationship("Organization", back_populates="translations")
    language = relationship("Language", back_populates="translations")

# ============================================================================
# Audit Logging
# ============================================================================
class AuditLog(Base):
    """Compliance and security audit trail"""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_org", "organization_id"),
        Index("idx_audit_logs_user", "user_id"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_date", "created_at"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50))
    entity_id = Column(UUID(as_uuid=True))
    old_values = Column(JSONB)
    new_values = Column(JSONB)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    status = Column(String(20), default="success")
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    organization = relationship("Organization", back_populates="audit_logs")
    user = relationship("User")

# ============================================================================
# Pydantic Schemas (for API validation)
# ============================================================================

class LanguageSchema(BaseModel):
    id: str
    code: str
    name: str
    is_active: bool
    
    class Config:
        from_attributes = True

class OrganizationSchema(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    settings: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True

class UserCreateSchema(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    phone: Optional[str] = None
    role: UserRole = UserRole.VIEWER
    preferred_language: str = "en"

class UserSchema(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: UserRole
    avatar_url: Optional[str] = None
    preferred_language: str
    is_active: bool
    last_login: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class PropertyAddressSchema(BaseModel):
    street: str
    city: str
    state: str
    zip: str
    country: str
    coordinates: Optional[Dict[str, float]] = None

class PropertyCreateSchema(BaseModel):
    type: str
    status: PropertyStatus = PropertyStatus.AVAILABLE
    mls_number: Optional[str] = None
    address: PropertyAddressSchema
    square_feet: Optional[Decimal] = None
    lot_size: Optional[Decimal] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[Decimal] = None
    year_built: Optional[int] = None
    list_price: Decimal
    rental_price: Optional[Decimal] = None
    currency: str = "USD"
    description: Optional[str] = None
    features: Optional[Dict[str, Any]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    
    @validator("list_price")
    def validate_price(cls, v):
        if v <= 0:
            raise ValueError("Price must be greater than 0")
        return v

class PropertySchema(PropertyCreateSchema):
    id: str
    organization_id: str
    listing_agent_id: Optional[str] = None
    primary_photo_url: Optional[str] = None
    photo_urls: List[str] = []
    video_url: Optional[str] = None
    virtual_tour_url: Optional[str] = None
    tags: List[str] = []
    price_history: List[Dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ClientCreateSchema(BaseModel):
    first_name: str
    last_name: str
    email: Optional[EmailStr] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    source: LeadSource
    source_details: Optional[str] = None
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    property_type_preferences: Optional[List[str]] = None
    location_preferences: Optional[Dict[str, Any]] = None
    preferred_contact_method: Optional[str] = None
    preferred_language: str = "en"

class ClientSchema(ClientCreateSchema):
    id: str
    organization_id: str
    full_name: str
    assigned_agent_id: Optional[str] = None
    is_active: bool
    last_contacted: Optional[datetime] = None
    acquisition_date: datetime
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class DealCreateSchema(BaseModel):
    client_id: str
    property_id: str
    deal_type: str  # sale, rental
    stage: DealStage = DealStage.INQUIRY
    proposed_price: Optional[Decimal] = None
    commission_percent: Optional[Decimal] = None
    internal_notes: Optional[str] = None
    expected_closing_date: Optional[datetime] = None

class DealSchema(DealCreateSchema):
    id: str
    organization_id: str
    agent_id: str
    agreed_price: Optional[Decimal] = None
    commission_amount: Optional[Decimal] = None
    closing_cost: Optional[Decimal] = None
    inquiry_date: datetime
    first_showing_date: Optional[datetime] = None
    offer_date: Optional[datetime] = None
    actual_closing_date: Optional[datetime] = None
    is_active: bool
    is_open: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class CallLogSchema(BaseModel):
    id: str
    client_id: Optional[str] = None
    agent_id: str
    call_type: CallType
    phone_number: Optional[str] = None
    duration_seconds: int
    transcript: Optional[str] = None
    ai_summary: Optional[str] = None
    key_topics: List[str] = []
    action_items: List[str] = []
    sentiment_label: Optional[str] = None
    call_quality: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

# ============================================================================
# API Response Models
# ============================================================================
class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    data: List[Dict[str, Any]]

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    status_code: int
