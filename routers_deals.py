"""
Deals API Routes
Endpoints for deal management, pipeline tracking, and commission calculation
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

from middleware_auth import (
    get_current_user, UserContext, require_role
)
from services_deals import DealService
from models import User, UserRole
from db import get_db

# ============================================================================
# Pydantic Models
# ============================================================================

class CreateDealRequest(BaseModel):
    client_id: str
    property_id: str
    deal_type: str = Field(default="sale", regex="^(sale|rental|lease)$")
    proposed_price: Optional[float] = Field(None, gt=0)
    offer_price: Optional[float] = Field(None, gt=0)
    earnest_money: Optional[float] = Field(None, ge=0)
    expected_close_date: Optional[datetime] = None
    notes: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None

class UpdateDealRequest(BaseModel):
    proposed_price: Optional[float] = Field(None, gt=0)
    offer_price: Optional[float] = Field(None, gt=0)
    earnest_money: Optional[float] = Field(None, ge=0)
    expected_close_date: Optional[datetime] = None
    notes: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(None, regex="^(active|inactive|won|lost)$")

class MoveStagRequest(BaseModel):
    new_stage: str = Field(..., regex="^(lead|offer|negotiation|inspection|appraisal|closed)$")
    reason: Optional[str] = None

class UpdateOfferRequest(BaseModel):
    offer_price: float = Field(..., gt=0)
    earnest_money: Optional[float] = Field(None, ge=0)

class CloseDealRequest(BaseModel):
    actual_close_date: Optional[datetime] = None
    final_price: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = None

class DealStageHistoryResponse(BaseModel):
    id: str
    deal_id: str
    from_stage: Optional[str]
    to_stage: str
    changed_by: str
    reason: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

class DealResponse(BaseModel):
    id: str
    organization_id: str
    client_id: str
    property_id: str
    agent_id: str
    type: str
    status: str
    stage: str
    proposed_price: float
    offer_price: Optional[float]
    earnest_money: Optional[float]
    expected_close_date: Optional[datetime]
    closed_at: Optional[datetime]
    notes: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class DealListResponse(BaseModel):
    deals: List[DealResponse]
    total: int
    skip: int
    limit: int

class PriceNegotiationResponse(BaseModel):
    proposed_price: float
    offer_price: float
    difference: float
    percentage_below: float
    earnest_money: Optional[float]

class CommissionResponse(BaseModel):
    sale_price: float
    commission_rate: float
    total_commission: float
    agent_commission: float
    broker_commission: float

class PipelineStatsResponse(BaseModel):
    total_active_deals: int
    by_stage: Dict[str, Dict[str, Any]]
    total_pipeline_value: float
    average_deal_value: float
    by_status: Dict[str, int]

class AgentPerformanceResponse(BaseModel):
    total_deals: int
    closed_deals: int
    close_rate: float
    pipeline_value: float
    average_deal_value: float
    average_days_to_close: int

class RevenueForecaseResponse(BaseModel):
    best_case: float
    worst_case: float
    probable: float

class DealStatsResponse(BaseModel):
    total_deals: int
    active_deals: int
    won_deals: int
    lost_deals: int
    win_rate: float
    active_percentage: float

# ============================================================================
# Router Setup
# ============================================================================

router = APIRouter(
    prefix="/deals",
    tags=["Deals"],
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        404: {"description": "Not found"},
    }
)

# ============================================================================
# CREATE Deal
# ============================================================================

@router.post(
    "",
    response_model=DealResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new deal",
    description="Create a deal from a property match (Agents and Admins only)",
)
async def create_deal(
    request: CreateDealRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> DealResponse:
    """
    Create a new deal
    
    - **client_id**: Client UUID
    - **property_id**: Property UUID
    - **deal_type**: sale, rental, or lease (default: sale)
    - **proposed_price**: Initial asking price (optional)
    - **offer_price**: Client's offer (optional)
    - **earnest_money**: Earnest money deposit (optional)
    - **expected_close_date**: When deal should close (optional)
    - **notes**: Deal notes
    - **custom_fields**: Any custom data
    
    Deal starts in 'lead' stage.
    """
    try:
        service = DealService(db)
        
        deal = service.create_deal(
            organization_id=current_user.organization_id,
            client_id=request.client_id,
            property_id=request.property_id,
            agent_id=current_user.user_id,
            deal_type=request.deal_type,
            proposed_price=request.proposed_price,
            offer_price=request.offer_price,
            earnest_money=request.earnest_money,
            expected_close_date=request.expected_close_date,
            notes=request.notes,
            custom_fields=request.custom_fields,
        )
        
        return DealResponse.model_validate(deal)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to create deal")

# ============================================================================
# LIST Deals
# ============================================================================

@router.get(
    "",
    response_model=DealListResponse,
    summary="List deals",
    description="List all deals in organization with filters",
)
async def list_deals(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None, regex="^(active|inactive|won|lost)?$"),
    stage: Optional[str] = Query(None),
    deal_type: Optional[str] = Query(None, regex="^(sale|rental|lease)?$"),
    sort_by: str = Query("created_at", regex="^(created_at|expected_close_date|offer_price)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DealListResponse:
    """
    List deals with filtering and pagination
    
    Query Parameters:
    - **skip**: Number of results to skip (default: 0)
    - **limit**: Number of results to return (default: 50, max: 100)
    - **status**: Filter by status (active, inactive, won, lost)
    - **stage**: Filter by stage (lead, offer, negotiation, inspection, appraisal, closed)
    - **deal_type**: Filter by type (sale, rental, lease)
    - **sort_by**: Sort field (created_at, expected_close_date, offer_price)
    - **sort_order**: Sort order (asc, desc)
    
    All users can list deals.
    """
    try:
        service = DealService(db)
        
        deals, total = service.list_deals(
            organization_id=current_user.organization_id,
            skip=skip,
            limit=limit,
            status=status,
            stage=stage,
            deal_type=deal_type,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        
        return DealListResponse(
            deals=[DealResponse.model_validate(d) for d in deals],
            total=total,
            skip=skip,
            limit=limit,
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to list deals")

# ============================================================================
# GET Deal Details
# ============================================================================

@router.get(
    "/{deal_id}",
    response_model=DealResponse,
    summary="Get deal details",
)
async def get_deal(
    deal_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DealResponse:
    """
    Get detailed information about a specific deal
    
    Includes:
    - Full deal information
    - Pipeline stage and history
    - Price negotiation details
    """
    try:
        service = DealService(db)
        deal = service.get_deal(
            deal_id=deal_id,
            organization_id=current_user.organization_id,
        )
        
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        
        return DealResponse.model_validate(deal)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get deal")

# ============================================================================
# UPDATE Deal
# ============================================================================

@router.patch(
    "/{deal_id}",
    response_model=DealResponse,
    summary="Update deal",
)
async def update_deal(
    deal_id: str,
    request: UpdateDealRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> DealResponse:
    """
    Update deal information
    
    Fields that can be updated:
    - proposed_price, offer_price, earnest_money
    - expected_close_date
    - notes, custom_fields
    - status (active, inactive, won, lost)
    """
    try:
        service = DealService(db)
        
        deal = service.get_deal(deal_id, current_user.organization_id)
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        
        # Build update dict
        update_dict = {k: v for k, v in request.model_dump().items() if v is not None}
        
        updated = service.update_deal(
            deal_id=deal_id,
            organization_id=current_user.organization_id,
            **update_dict
        )
        
        return DealResponse.model_validate(updated)
    
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to update deal")

# ============================================================================
# PIPELINE MANAGEMENT
# ============================================================================

@router.patch(
    "/{deal_id}/stage",
    response_model=DealResponse,
    summary="Move deal to stage",
    description="Move deal to next pipeline stage",
)
async def move_to_stage(
    deal_id: str,
    request: MoveStagRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> DealResponse:
    """
    Move deal to next pipeline stage
    
    Stages (in order):
    1. **lead** - Initial prospect
    2. **offer** - Formal offer submitted
    3. **negotiation** - Price/terms negotiation
    4. **inspection** - Property inspection pending
    5. **appraisal** - Appraisal in progress
    6. **closed** - Deal completed
    
    Provides reason for audit trail.
    """
    try:
        service = DealService(db)
        
        deal = service.move_to_stage(
            deal_id=deal_id,
            organization_id=current_user.organization_id,
            new_stage=request.new_stage,
            changed_by_id=current_user.user_id,
            reason=request.reason,
        )
        
        return DealResponse.model_validate(deal)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to move deal")

@router.get(
    "/{deal_id}/history",
    response_model=List[DealStageHistoryResponse],
    summary="Get deal stage history",
    description="Get complete stage transition history",
)
async def get_stage_history(
    deal_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[DealStageHistoryResponse]:
    """
    Get complete pipeline history for a deal
    
    Shows all stage transitions with:
    - From stage and to stage
    - User who made change
    - Reason for change
    - Timestamp
    """
    try:
        service = DealService(db)
        
        # Verify deal exists
        deal = service.get_deal(deal_id, current_user.organization_id)
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        
        history = service.get_stage_history(deal_id)
        
        return [DealStageHistoryResponse.model_validate(h) for h in history]
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get stage history")

# ============================================================================
# PRICE & OFFER MANAGEMENT
# ============================================================================

@router.patch(
    "/{deal_id}/offer",
    response_model=DealResponse,
    summary="Update offer price",
    description="Update offer during negotiation",
)
async def update_offer(
    deal_id: str,
    request: UpdateOfferRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> DealResponse:
    """
    Update offer price and earnest money
    
    Useful for:
    - Buyer counter-offers
    - Seller price reductions
    - Earnest money adjustments
    """
    try:
        service = DealService(db)
        
        deal = service.update_offer(
            deal_id=deal_id,
            organization_id=current_user.organization_id,
            offer_price=request.offer_price,
            earnest_money=request.earnest_money,
            user_id=current_user.user_id,
        )
        
        return DealResponse.model_validate(deal)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to update offer")

@router.get(
    "/{deal_id}/negotiation",
    response_model=PriceNegotiationResponse,
    summary="Get price negotiation summary",
    description="Get price negotiation details",
)
async def get_price_negotiation(
    deal_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PriceNegotiationResponse:
    """
    Get price negotiation summary
    
    Shows:
    - Proposed price (asking)
    - Current offer
    - Difference and percentage
    - Earnest money
    """
    try:
        service = DealService(db)
        
        deal = service.get_deal(deal_id, current_user.organization_id)
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        
        negotiation = service.get_price_negotiation(deal_id)
        
        return PriceNegotiationResponse(**negotiation)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get negotiation data")

# ============================================================================
# COMMISSION MANAGEMENT
# ============================================================================

@router.get(
    "/{deal_id}/commission",
    response_model=CommissionResponse,
    summary="Calculate deal commission",
    description="Calculate commission based on deal price",
)
async def calculate_commission(
    deal_id: str,
    rate: float = Query(0.05, ge=0.01, le=0.20, description="Commission rate (0.01-0.20)"),
    current_user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CommissionResponse:
    """
    Calculate commission
    
    Query Parameters:
    - **rate**: Commission percentage as decimal (default: 0.05 = 5%)
    
    Returns:
    - Total commission (split between agent and broker)
    - Agent commission (50% of total)
    - Broker commission (50% of total)
    """
    try:
        service = DealService(db)
        
        deal = service.get_deal(deal_id, current_user.organization_id)
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        
        commission = service.calculate_commission(deal_id, rate)
        
        return CommissionResponse(**commission)
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to calculate commission")

# ============================================================================
# CLOSE DEAL
# ============================================================================

@router.post(
    "/{deal_id}/close",
    response_model=DealResponse,
    summary="Close deal",
    description="Mark deal as won/closed",
)
async def close_deal(
    deal_id: str,
    request: CloseDealRequest,
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> DealResponse:
    """
    Close a deal (mark as won)
    
    - **actual_close_date**: When deal closed (optional, defaults to now)
    - **final_price**: Final sale price (optional)
    - **notes**: Closing notes
    """
    try:
        service = DealService(db)
        
        deal = service.close_deal(
            deal_id=deal_id,
            organization_id=current_user.organization_id,
            actual_close_date=request.actual_close_date,
            final_price=request.final_price,
            user_id=current_user.user_id,
            notes=request.notes,
        )
        
        return DealResponse.model_validate(deal)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to close deal")

@router.post(
    "/{deal_id}/lose",
    response_model=DealResponse,
    summary="Mark deal as lost",
)
async def lose_deal(
    deal_id: str,
    reason: Optional[str] = Query(None),
    current_user: UserContext = Depends(require_role(UserRole.AGENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> DealResponse:
    """
    Mark deal as lost
    
    Query Parameters:
    - **reason**: Reason deal was lost (optional)
    """
    try:
        service = DealService(db)
        
        deal = service.lose_deal(
            deal_id=deal_id,
            organization_id=current_user.organization_id,
            reason=reason,
            user_id=current_user.user_id,
        )
        
        return DealResponse.model_validate(deal)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to lose deal")

# ============================================================================
# ANALYTICS & REPORTING
# ============================================================================

@router.get(
    "/admin/pipeline",
    response_model=PipelineStatsResponse,
    summary="Get pipeline statistics",
    description="Get organization pipeline stats",
)
async def get_pipeline_stats(
    current_user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> PipelineStatsResponse:
    """
    Get complete pipeline statistics
    
    Includes:
    - Total active deals
    - Deals by stage with count and total value
    - Total pipeline value
    - Average deal value
    """
    try:
        service = DealService(db)
        
        stats = service.get_pipeline_stats(current_user.organization_id)
        
        return PipelineStatsResponse(**stats)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get pipeline stats")

@router.get(
    "/admin/agent-performance",
    response_model=AgentPerformanceResponse,
    summary="Get agent performance",
    description="Get performance metrics for all agents or specific agent",
)
async def get_agent_performance(
    agent_id: Optional[str] = Query(None),
    current_user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AgentPerformanceResponse:
    """
    Get agent performance metrics
    
    Query Parameters:
    - **agent_id**: Optional specific agent (default: all agents)
    
    Returns:
    - Total deals handled
    - Closed deals
    - Close rate (percentage)
    - Pipeline value
    - Average deal value
    - Average days to close
    """
    try:
        service = DealService(db)
        
        performance = service.get_agent_performance(
            organization_id=current_user.organization_id,
            agent_id=agent_id,
        )
        
        return AgentPerformanceResponse(**performance)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get agent performance")

@router.get(
    "/admin/forecast",
    response_model=RevenueForecaseResponse,
    summary="Forecast revenue",
    description="Forecast expected revenue from pipeline",
)
async def forecast_revenue(
    commission_rate: float = Query(0.05, ge=0.01, le=0.20),
    current_user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> RevenueForecaseResponse:
    """
    Forecast expected revenue
    
    Query Parameters:
    - **commission_rate**: Commission percentage (default: 0.05 = 5%)
    
    Returns:
    - **best_case**: All deals close
    - **worst_case**: No deals close
    - **probable**: Based on stage close probabilities
    """
    try:
        service = DealService(db)
        
        forecast = service.forecast_revenue(
            organization_id=current_user.organization_id,
            commission_rate=commission_rate,
        )
        
        return RevenueForecaseResponse(**forecast)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to forecast revenue")

# ============================================================================
# STATISTICS
# ============================================================================

@router.get(
    "/admin/stats",
    response_model=DealStatsResponse,
    summary="Get deal statistics",
    description="Get organization-wide deal statistics",
)
async def get_deal_stats(
    current_user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> DealStatsResponse:
    """
    Get deal statistics for the organization
    
    Metrics:
    - Total deals
    - Active deals
    - Won deals
    - Lost deals
    - Win rate percentage
    - Active percentage
    """
    try:
        service = DealService(db)
        
        stats = service.get_deal_stats(current_user.organization_id)
        
        return DealStatsResponse(**stats)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to get statistics")

# ============================================================================
# ARCHIVE
# ============================================================================

@router.post(
    "/{deal_id}/archive",
    response_model=DealResponse,
    summary="Archive deal",
)
async def archive_deal(
    deal_id: str,
    reason: Optional[str] = Query(None),
    current_user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> DealResponse:
    """
    Archive a deal
    
    Archived deals:
    - Are hidden from default listings
    - Can be searched/filtered
    - All data is preserved
    """
    try:
        service = DealService(db)
        
        deal = service.archive_deal(
            deal_id=deal_id,
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
            reason=reason,
        )
        
        return DealResponse.model_validate(deal)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to archive deal")
