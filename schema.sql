-- Real Estate CRM Database Schema
-- PostgreSQL 15+
-- Features: Audit trails, JSONB for flexibility, full-text search, role-based access

-- ============================================================================
-- Extensions
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search
CREATE EXTENSION IF NOT EXISTS "ltree";    -- For hierarchical organization structures

-- ============================================================================
-- Enums
-- ============================================================================
CREATE TYPE user_role AS ENUM ('admin', 'agent', 'viewer');
CREATE TYPE property_status AS ENUM ('available', 'reserved', 'sold', 'rented', 'delisted');
CREATE TYPE deal_stage AS ENUM ('inquiry', 'showing', 'offer', 'negotiation', 'contingent', 'closing', 'closed', 'lost');
CREATE TYPE lead_source AS ENUM ('website', 'referral', 'cold_call', 'email', 'social_media', 'walk_in', 'other');
CREATE TYPE call_type AS ENUM ('inbound', 'outbound', 'callback');

-- ============================================================================
-- Core Language Support
-- ============================================================================
CREATE TABLE languages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR(5) NOT NULL UNIQUE, -- 'en', 'ru', 'hy', 'fa'
    name VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

INSERT INTO languages (code, name) VALUES 
    ('en', 'English'),
    ('ru', 'Русский'),
    ('hy', 'Հայերեն'),
    ('fa', 'فارسی');

-- ============================================================================
-- Organizations & Users
-- ============================================================================
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    logo_url TEXT,
    website VARCHAR(255),
    phone VARCHAR(20),
    address JSONB, -- { street, city, state, zip, country }
    settings JSONB DEFAULT '{"default_language": "en", "currency": "USD", "timezone": "UTC"}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(20),
    role user_role NOT NULL DEFAULT 'viewer',
    avatar_url TEXT,
    preferred_language VARCHAR(5) DEFAULT 'en',
    is_active BOOLEAN DEFAULT true,
    last_login TIMESTAMP,
    email_verified BOOLEAN DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    UNIQUE(organization_id, email),
    FOREIGN KEY (preferred_language) REFERENCES languages(code)
);

CREATE INDEX idx_users_org_role ON users(organization_id, role);
CREATE INDEX idx_users_email ON users(email);

-- ============================================================================
-- Multilingual Content Tables
-- ============================================================================
CREATE TABLE translations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    language_id UUID NOT NULL REFERENCES languages(id) ON DELETE CASCADE,
    entity_type VARCHAR(50) NOT NULL, -- 'property_description', 'listing_title', 'deal_note'
    entity_id UUID NOT NULL,
    key VARCHAR(255),
    value TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    UNIQUE(organization_id, language_id, entity_type, entity_id, key)
);

CREATE INDEX idx_translations_entity ON translations(entity_type, entity_id);

-- ============================================================================
-- Properties
-- ============================================================================
CREATE TABLE properties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    listing_agent_id UUID REFERENCES users(id) ON DELETE SET NULL,
    
    -- Basic Info
    type VARCHAR(50) NOT NULL, -- 'apartment', 'house', 'commercial', 'land'
    status property_status NOT NULL DEFAULT 'available',
    mls_number VARCHAR(100),
    
    -- Location & Details
    address JSONB NOT NULL, -- { street, city, state, zip, country, coordinates }
    square_feet DECIMAL(10,2),
    lot_size DECIMAL(10,2),
    bedrooms INT,
    bathrooms DECIMAL(4,2),
    year_built INT,
    features JSONB DEFAULT '{}', -- { pool, garage, fireplace, renovated, etc }
    
    -- Pricing
    list_price DECIMAL(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    rental_price DECIMAL(12,2),
    price_history JSONB DEFAULT '[]', -- [{price, date, reason}]
    
    -- Media
    primary_photo_url TEXT,
    photo_urls TEXT[] DEFAULT '{}',
    video_url TEXT,
    virtual_tour_url TEXT,
    
    -- Status & Tracking
    description TEXT,
    tags VARCHAR(255)[] DEFAULT '{}',
    custom_fields JSONB DEFAULT '{}', -- Extensible for custom data
    
    -- Audit
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP,
    
    CONSTRAINT valid_price CHECK (list_price > 0)
);

CREATE INDEX idx_properties_org_status ON properties(organization_id, status);
CREATE INDEX idx_properties_location ON properties USING GIST(address);
CREATE INDEX idx_properties_agent ON properties(listing_agent_id);
CREATE INDEX idx_properties_mls ON properties(mls_number);

-- Property audit trail
CREATE TABLE property_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    changed_by UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    field_name VARCHAR(100),
    old_value TEXT,
    new_value TEXT,
    change_type VARCHAR(50), -- 'status_change', 'price_update', 'photo_added', 'listing_created'
    change_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_property_history_property ON property_history(property_id);
CREATE INDEX idx_property_history_date ON property_history(created_at DESC);

-- ============================================================================
-- Clients & Leads
-- ============================================================================
CREATE TABLE clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    
    -- Personal Info
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    phone_primary VARCHAR(20),
    phone_secondary VARCHAR(20),
    date_of_birth DATE,
    
    -- Lead Information
    source lead_source NOT NULL,
    source_details TEXT,
    acquisition_date TIMESTAMP DEFAULT NOW(),
    
    -- Preferences
    preferred_contact_method VARCHAR(50), -- 'email', 'phone', 'sms'
    preferred_language VARCHAR(5),
    do_not_contact BOOLEAN DEFAULT false,
    do_not_call BOOLEAN DEFAULT false,
    
    -- Financial
    budget_min DECIMAL(12,2),
    budget_max DECIMAL(12,2),
    financial_preapproval_url TEXT,
    
    -- Search Preferences
    property_type_preferences VARCHAR(50)[],
    location_preferences JSONB DEFAULT '{}', -- { cities[], zipcodes[], states[] }
    bedroom_preferences INT,
    bathroom_preferences DECIMAL(4,2),
    must_have_features VARCHAR(255)[],
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    assigned_agent_id UUID REFERENCES users(id) ON DELETE SET NULL,
    last_contacted TIMESTAMP,
    
    -- Custom Data
    custom_fields JSONB DEFAULT '{}',
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP
);

CREATE INDEX idx_clients_org ON clients(organization_id);
CREATE INDEX idx_clients_agent ON clients(assigned_agent_id);
CREATE INDEX idx_clients_email ON clients(email);
CREATE INDEX idx_clients_phone ON clients(phone_primary);

-- ============================================================================
-- Client Contact History
-- ============================================================================
CREATE TABLE client_interactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    
    interaction_type VARCHAR(50) NOT NULL, -- 'call', 'email', 'sms', 'showing', 'note'
    direction VARCHAR(20), -- 'inbound', 'outbound' (for calls/emails)
    subject VARCHAR(255),
    content TEXT,
    duration_seconds INT, -- for calls
    
    -- Call Logging
    call_transcript TEXT,
    call_summary TEXT,
    call_recording_url TEXT,
    call_sentiment VARCHAR(50), -- 'positive', 'neutral', 'negative'
    
    -- Property Reference
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    
    -- Status
    follow_up_required BOOLEAN DEFAULT false,
    follow_up_date TIMESTAMP,
    next_step TEXT,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_interactions_client ON client_interactions(client_id);
CREATE INDEX idx_interactions_agent ON client_interactions(agent_id);
CREATE INDEX idx_interactions_property ON client_interactions(property_id);
CREATE INDEX idx_interactions_date ON client_interactions(created_at DESC);
CREATE INDEX idx_interactions_type ON client_interactions(interaction_type);

-- ============================================================================
-- Deal Pipeline
-- ============================================================================
CREATE TABLE deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    
    -- Deal Info
    deal_type VARCHAR(50) NOT NULL, -- 'sale', 'rental'
    stage deal_stage NOT NULL DEFAULT 'inquiry',
    
    -- Financial
    proposed_price DECIMAL(12,2),
    agreed_price DECIMAL(12,2),
    commission_percent DECIMAL(5,2),
    commission_amount DECIMAL(12,2),
    closing_cost DECIMAL(12,2),
    
    -- Timeline
    inquiry_date TIMESTAMP DEFAULT NOW(),
    first_showing_date TIMESTAMP,
    offer_date TIMESTAMP,
    expected_closing_date TIMESTAMP,
    actual_closing_date TIMESTAMP,
    
    -- Notes
    internal_notes TEXT,
    client_notes TEXT,
    contingencies TEXT,
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP
);

CREATE INDEX idx_deals_org ON deals(organization_id);
CREATE INDEX idx_deals_client ON deals(client_id);
CREATE INDEX idx_deals_property ON deals(property_id);
CREATE INDEX idx_deals_agent ON deals(agent_id);
CREATE INDEX idx_deals_stage ON deals(stage);

-- Deal stage history for audit trail
CREATE TABLE deal_stage_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deal_id UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    from_stage deal_stage,
    to_stage deal_stage NOT NULL,
    changed_by UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Property Showings
-- ============================================================================
CREATE TABLE showings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    
    scheduled_time TIMESTAMP NOT NULL,
    duration_minutes INT DEFAULT 60,
    status VARCHAR(50) NOT NULL, -- 'scheduled', 'completed', 'cancelled', 'no_show'
    
    feedback TEXT,
    client_interest_level INT, -- 1-5
    follow_up_needed BOOLEAN DEFAULT false,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_showings_property ON showings(property_id);
CREATE INDEX idx_showings_client ON showings(client_id);
CREATE INDEX idx_showings_agent ON showings(agent_id);
CREATE INDEX idx_showings_time ON showings(scheduled_time);

-- ============================================================================
-- Property Matching Cache
-- ============================================================================
CREATE TABLE property_matches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    
    match_score DECIMAL(5,2), -- 0-100
    match_reason JSONB, -- { reasons: ['price_match', 'location_match', 'features_match'] }
    viewed_at TIMESTAMP,
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    UNIQUE(client_id, property_id)
);

CREATE INDEX idx_property_matches_client ON property_matches(client_id);
CREATE INDEX idx_property_matches_score ON property_matches(match_score DESC);

-- ============================================================================
-- Call Logs (Detailed)
-- ============================================================================
CREATE TABLE call_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    agent_id UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    
    call_type call_type NOT NULL,
    phone_number VARCHAR(20),
    duration_seconds INT NOT NULL,
    
    transcript TEXT,
    transcript_language VARCHAR(5),
    ai_summary TEXT,
    key_topics VARCHAR(255)[],
    action_items TEXT[],
    
    recording_url TEXT,
    recording_duration_seconds INT,
    
    sentiment_score DECIMAL(3,2), -- -1 to 1
    sentiment_label VARCHAR(50), -- 'positive', 'neutral', 'negative'
    
    call_quality VARCHAR(50), -- 'excellent', 'good', 'fair', 'poor'
    
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_call_logs_org ON call_logs(organization_id);
CREATE INDEX idx_call_logs_client ON call_logs(client_id);
CREATE INDEX idx_call_logs_agent ON call_logs(agent_id);
CREATE INDEX idx_call_logs_date ON call_logs(created_at DESC);
CREATE INDEX idx_call_logs_transcript ON call_logs USING GIN (to_tsvector('english', transcript));

-- ============================================================================
-- Audit Log (for compliance & security)
-- ============================================================================
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL, -- 'user_login', 'data_exported', 'deal_closed', etc
    entity_type VARCHAR(50),
    entity_id UUID,
    old_values JSONB,
    new_values JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_org ON audit_logs(organization_id);
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_date ON audit_logs(created_at DESC);

-- ============================================================================
-- Reporting Views
-- ============================================================================
CREATE VIEW agent_performance AS
SELECT 
    u.id,
    u.first_name,
    u.last_name,
    COUNT(DISTINCT d.id) as total_deals,
    COUNT(DISTINCT CASE WHEN d.stage = 'closed' THEN d.id END) as closed_deals,
    COUNT(DISTINCT CASE WHEN d.stage = 'closed' THEN d.id END)::FLOAT / 
        NULLIF(COUNT(DISTINCT d.id), 0) as close_rate,
    SUM(d.commission_amount) as total_commission,
    AVG(d.commission_amount) as avg_commission,
    COUNT(DISTINCT c.id) as total_clients
FROM users u
LEFT JOIN deals d ON u.id = d.agent_id
LEFT JOIN clients c ON u.id = c.assigned_agent_id
WHERE u.role = 'agent'
GROUP BY u.id, u.first_name, u.last_name;

CREATE VIEW pipeline_forecast AS
SELECT 
    stage,
    COUNT(*) as count,
    SUM(proposed_price) as potential_revenue,
    AVG(proposed_price) as avg_deal_size,
    COUNT(CASE WHEN is_active = true THEN 1 END) as active_deals
FROM deals
WHERE deleted_at IS NULL
GROUP BY stage;

-- ============================================================================
-- Triggers for Audit Trail
-- ============================================================================
CREATE OR REPLACE FUNCTION audit_property_changes()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO property_history (
        property_id, 
        changed_by, 
        field_name, 
        old_value, 
        new_value,
        change_type
    ) VALUES (
        NEW.id,
        COALESCE(current_setting('app.current_user_id')::uuid, NULL),
        TG_ARGV[0],
        OLD::text,
        NEW::text,
        'auto_update'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for status changes
CREATE TRIGGER property_status_changed
AFTER UPDATE OF status ON properties
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION audit_property_changes('status');
