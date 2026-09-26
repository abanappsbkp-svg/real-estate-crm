"""
Deals Service
Business logic for deal management, pipeline tracking, and commission calculation
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
import uuid
from models import as_uuid

from models import (
    Deal, DealStageHistory, Client, Property, User, UserRole, 
    AuditLog, Organization, PropertyMatch, ClientInteraction
)

class DealService:
    """Service for deal management and pipeline operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ========================================================================
    # Create & Initialize Deals
    # ========================================================================
    
    def create_deal(
        self,
        organization_id: str,
        client_id: str,
        property_id: str,
        agent_id: str,
        deal_type: str = "sale",  # sale, rental, lease
        status: str = "active",  # active, inactive, won, lost
        proposed_price: Optional[float] = None,
        offer_price: Optional[float] = None,
        earnest_money: Optional[float] = None,
        stage: str = "lead",  # lead, offer, negotiation, inspection, appraisal, closed
        expected_close_date: Optional[datetime] = None,
        notes: Optional[str] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> Deal:
        """
        Create a new deal from a property match
        
        Args:
            organization_id: Organization UUID
            client_id: Client UUID
            property_id: Property UUID
            agent_id: Agent managing the deal
            deal_type: sale, rental, or lease
            status: active, inactive, won, lost
            proposed_price: Initial asking price
            offer_price: Client's offer price
            earnest_money: Earnest money deposit
            stage: Pipeline stage
            expected_close_date: Expected closing date
            notes: Deal notes
            custom_fields: Custom deal data
        
        Returns:
            Created Deal object
        """
        # Get property for context
        property_obj = self.db.query(Property).filter(
            Property.id == as_uuid(property_id)
        ).first()
        
        if not property_obj:
            raise ValueError("Property not found")
        
        deal = Deal(
            organization_id=as_uuid(organization_id),
            client_id=as_uuid(client_id),
            property_id=as_uuid(property_id),
            agent_id=as_uuid(agent_id),
            type=deal_type,
            status=status,
            stage=stage,
            proposed_price=proposed_price or float(property_obj.list_price),
            offer_price=offer_price,
            earnest_money=earnest_money,
            expected_close_date=expected_close_date,
            notes=notes,
            custom_fields=custom_fields or {},
            is_active=True,
        )
        
        self.db.add(deal)
        self.db.flush()
        
        # Create initial stage history
        stage_history = DealStageHistory(
            deal_id=deal.id,
            from_stage=None,
            to_stage=stage,
            changed_by=as_uuid(agent_id),
            reason="Deal created",
        )
        self.db.add(stage_history)
        self.db.commit()
        self.db.refresh(deal)
        
        # Log creation
        self._log_audit(
            organization_id=organization_id,
            user_id=agent_id,
            action="deal_created",
            entity_type="deal",
            entity_id=str(deal.id),
            new_values={
                "client_id": client_id,
                "property_id": property_id,
                "type": deal_type,
                "stage": stage,
                "proposed_price": proposed_price,
            },
        )
        
        return deal
    
    # ========================================================================
    # Read & Retrieve Deals
    # ========================================================================
    
    def get_deal(
        self,
        deal_id: str,
        organization_id: Optional[str] = None
    ) -> Optional[Deal]:
        """Get deal by ID"""
        query = self.db.query(Deal).filter(
            Deal.id == as_uuid(deal_id),
        )
        
        if organization_id:
            query = query.filter(Deal.organization_id == as_uuid(organization_id))
        
        return query.first()
    
    def list_deals(
        self,
        organization_id: str,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        deal_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        client_id: Optional[str] = None,
        property_id: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[List[Deal], int]:
        """
        List deals with filters
        
        Args:
            organization_id: Organization UUID
            skip: Number to skip
            limit: Number to return
            status: active, inactive, won, lost
            stage: Pipeline stage
            deal_type: sale, rental, lease
            agent_id: Filter by agent
            client_id: Filter by client
            property_id: Filter by property
            search_query: Search by client or property name
            sort_by: created_at, expected_close_date, offer_price
            sort_order: asc or desc
        
        Returns:
            Tuple of (deals list, total count)
        """
        query = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id),
        )
        
        # Apply filters
        if status:
            query = query.filter(Deal.status == status)
        
        if stage:
            query = query.filter(Deal.stage == stage)
        
        if deal_type:
            query = query.filter(Deal.type == deal_type)
        
        if agent_id:
            query = query.filter(Deal.agent_id == as_uuid(agent_id))
        
        if client_id:
            query = query.filter(Deal.client_id == as_uuid(client_id))
        
        if property_id:
            query = query.filter(Deal.property_id == as_uuid(property_id))
        
        if search_query:
            # Would need to join with Client/Property tables for better search
            search_term = f"%{search_query}%"
            # Basic search on deal notes
            query = query.filter(Deal.notes.ilike(search_term))
        
        # Count total
        total = query.count()
        
        # Sort
        if sort_by == "expected_close_date":
            query = query.order_by(
                Deal.expected_close_date.desc() if sort_order == "desc" else Deal.expected_close_date.asc()
            )
        elif sort_by == "offer_price":
            query = query.order_by(
                Deal.offer_price.desc() if sort_order == "desc" else Deal.offer_price.asc()
            )
        else:  # created_at
            query = query.order_by(
                Deal.created_at.desc() if sort_order == "desc" else Deal.created_at.asc()
            )
        
        # Pagination
        deals = query.offset(skip).limit(limit).all()
        
        return deals, total
    
    # ========================================================================
    # Update Deal
    # ========================================================================
    
    def update_deal(
        self,
        deal_id: str,
        organization_id: str,
        **kwargs
    ) -> Deal:
        """
        Update deal information
        
        Args:
            deal_id: Deal UUID
            organization_id: Organization UUID
            **kwargs: Fields to update
        
        Returns:
            Updated Deal object
        """
        deal = self.get_deal(deal_id, organization_id)
        
        if not deal:
            raise ValueError("Deal not found")
        
        old_values = {}
        new_values = {}
        
        # Allowed fields
        allowed_fields = {
            'proposed_price', 'offer_price', 'earnest_money',
            'expected_close_date', 'notes', 'custom_fields',
            'status', 'type'
        }
        
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                old_values[field] = getattr(deal, field)
                setattr(deal, field, value)
                new_values[field] = value
        
        deal.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(deal)
        
        # Log update
        if new_values:
            self._log_audit(
                organization_id=organization_id,
                user_id=None,
                action="deal_updated",
                entity_type="deal",
                entity_id=deal_id,
                old_values=old_values,
                new_values=new_values,
            )
        
        return deal
    
    # ========================================================================
    # Pipeline Management
    # ========================================================================
    
    def move_to_stage(
        self,
        deal_id: str,
        organization_id: str,
        new_stage: str,
        changed_by_id: str,
        reason: Optional[str] = None,
    ) -> Deal:
        """
        Move deal to next pipeline stage
        
        Stages: lead → offer → negotiation → inspection → appraisal → closed
        
        Args:
            deal_id: Deal UUID
            organization_id: Organization UUID
            new_stage: Target stage
            changed_by_id: User making change
            reason: Reason for stage change
        
        Returns:
            Updated Deal object
        """
        deal = self.get_deal(deal_id, organization_id)
        
        if not deal:
            raise ValueError("Deal not found")
        
        # Validate stage transition
        valid_stages = ["lead", "offer", "negotiation", "inspection", "appraisal", "closed"]
        if new_stage not in valid_stages:
            raise ValueError(f"Invalid stage: {new_stage}")
        
        old_stage = deal.stage
        deal.stage = new_stage
        deal.updated_at = datetime.utcnow()
        
        # Create stage history
        stage_history = DealStageHistory(
            deal_id=as_uuid(deal_id),
            from_stage=old_stage,
            to_stage=new_stage,
            changed_by=as_uuid(changed_by_id),
            reason=reason,
        )
        self.db.add(stage_history)
        self.db.commit()
        self.db.refresh(deal)
        
        # Log change
        self._log_audit(
            organization_id=organization_id,
            user_id=changed_by_id,
            action="deal_stage_moved",
            entity_type="deal",
            entity_id=deal_id,
            old_values={"stage": old_stage},
            new_values={"stage": new_stage, "reason": reason},
        )
        
        return deal
    
    def get_stage_history(self, deal_id: str) -> List[DealStageHistory]:
        """Get complete stage transition history for a deal"""
        return self.db.query(DealStageHistory).filter(
            DealStageHistory.deal_id == as_uuid(deal_id)
        ).order_by(DealStageHistory.created_at.asc()).all()
    
    def get_stage_duration(self, deal_id: str, stage: str) -> Optional[int]:
        """
        Get duration (in days) deal spent in a stage
        
        Returns: Number of days, or None if still in stage
        """
        history = self.get_stage_history(deal_id)
        
        stage_entry = None
        stage_exit = None
        
        for entry in history:
            if entry.to_stage == stage:
                stage_entry = entry.created_at
            elif entry.from_stage == stage:
                stage_exit = entry.created_at
                break
        
        if not stage_entry:
            return None
        
        if stage_exit:
            return (stage_exit - stage_entry).days
        
        return None  # Still in stage
    
    # ========================================================================
    # Price & Offer Management
    # ========================================================================
    
    def update_offer(
        self,
        deal_id: str,
        organization_id: str,
        offer_price: float,
        earnest_money: Optional[float] = None,
        user_id: Optional[str] = None,
    ) -> Deal:
        """Update offer price (can change during negotiation)"""
        deal = self.get_deal(deal_id, organization_id)
        
        if not deal:
            raise ValueError("Deal not found")
        
        old_price = deal.offer_price
        deal.offer_price = offer_price
        
        if earnest_money is not None:
            deal.earnest_money = earnest_money
        
        deal.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(deal)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="deal_offer_updated",
            entity_type="deal",
            entity_id=deal_id,
            old_values={"offer_price": old_price},
            new_values={"offer_price": offer_price},
        )
        
        return deal
    
    def get_price_negotiation(self, deal_id: str) -> Dict[str, Any]:
        """
        Get price negotiation summary
        
        Returns: {
            proposed_price: original asking,
            offer_price: current offer,
            difference: asking - offer,
            percentage: (difference / asking) * 100,
            earnest_money: deposit
        }
        """
        deal = self.get_deal(deal_id)
        
        if not deal:
            raise ValueError("Deal not found")
        
        proposed = float(deal.proposed_price or 0)
        offer = float(deal.offer_price or 0)
        difference = proposed - offer if offer > 0 else proposed
        percentage = (difference / proposed * 100) if proposed > 0 else 0
        
        return {
            "proposed_price": proposed,
            "offer_price": offer or proposed,
            "difference": difference,
            "percentage_below": percentage,
            "earnest_money": deal.earnest_money,
        }
    
    # ========================================================================
    # Commission Management
    # ========================================================================
    
    def calculate_commission(
        self,
        deal_id: str,
        commission_rate: float = 0.05,  # 5% default
    ) -> Dict[str, float]:
        """
        Calculate commission based on deal price
        
        Args:
            deal_id: Deal UUID
            commission_rate: Commission percentage (0-1)
        
        Returns:
            {
                sale_price: final price,
                total_commission: commission_rate * sale_price,
                agent_commission: (commission_rate / 2) * sale_price,
                broker_commission: (commission_rate / 2) * sale_price
            }
        """
        deal = self.get_deal(deal_id)
        
        if not deal:
            raise ValueError("Deal not found")
        
        # Use offer price if available, otherwise proposed
        sale_price = float(deal.offer_price or deal.proposed_price)
        
        total_commission = sale_price * commission_rate
        agent_commission = total_commission / 2
        broker_commission = total_commission / 2
        
        return {
            "sale_price": sale_price,
            "commission_rate": commission_rate,
            "total_commission": total_commission,
            "agent_commission": agent_commission,
            "broker_commission": broker_commission,
        }
    
    # ========================================================================
    # Close Deal
    # ========================================================================
    
    def close_deal(
        self,
        deal_id: str,
        organization_id: str,
        actual_close_date: Optional[datetime] = None,
        final_price: Optional[float] = None,
        user_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Deal:
        """
        Close a deal (mark as won)
        
        Args:
            deal_id: Deal UUID
            organization_id: Organization UUID
            actual_close_date: When deal closed
            final_price: Final sale price
            user_id: User closing the deal
            notes: Closing notes
        
        Returns:
            Closed Deal object
        """
        deal = self.get_deal(deal_id, organization_id)
        
        if not deal:
            raise ValueError("Deal not found")
        
        old_status = deal.status
        deal.status = "won"
        deal.stage = "closed"
        deal.closed_at = actual_close_date or datetime.utcnow()
        deal.is_active = False
        
        if final_price:
            deal.offer_price = final_price
        
        self.db.commit()
        self.db.refresh(deal)
        
        # Create final stage history
        stage_history = DealStageHistory(
            deal_id=as_uuid(deal_id),
            from_stage="appraisal",
            to_stage="closed",
            changed_by=as_uuid(user_id) if user_id else None,
            reason="Deal closed",
        )
        self.db.add(stage_history)
        self.db.commit()
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="deal_closed",
            entity_type="deal",
            entity_id=deal_id,
            old_values={"status": old_status, "is_active": True},
            new_values={"status": "won", "is_active": False, "notes": notes},
        )
        
        return deal
    
    def lose_deal(
        self,
        deal_id: str,
        organization_id: str,
        reason: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Deal:
        """Mark deal as lost"""
        deal = self.get_deal(deal_id, organization_id)
        
        if not deal:
            raise ValueError("Deal not found")
        
        deal.status = "lost"
        deal.is_active = False
        deal.closed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(deal)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="deal_lost",
            entity_type="deal",
            entity_id=deal_id,
            new_values={"reason": reason or "unknown"},
        )
        
        return deal
    
    # ========================================================================
    # Pipeline Analytics
    # ========================================================================
    
    def get_pipeline_stats(self, organization_id: str) -> Dict[str, Any]:
        """Get pipeline statistics for organization"""
        deals = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id),
            Deal.is_active == True,
        ).all()
        
        stats = {
            "total_active_deals": len(deals),
            "by_stage": {},
            "total_pipeline_value": 0.0,
            "average_deal_value": 0.0,
            "by_status": {"active": 0, "won": 0, "lost": 0},
        }
        
        for deal in deals:
            # By stage
            if deal.stage not in stats["by_stage"]:
                stats["by_stage"][deal.stage] = {"count": 0, "value": 0.0}
            
            stats["by_stage"][deal.stage]["count"] += 1
            deal_value = float(deal.offer_price or deal.proposed_price)
            stats["by_stage"][deal.stage]["value"] += deal_value
            stats["total_pipeline_value"] += deal_value
        
        # By status
        all_deals = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id)
        ).all()
        
        for deal in all_deals:
            if deal.status in stats["by_status"]:
                stats["by_status"][deal.status] += 1
        
        # Average
        if len(deals) > 0:
            stats["average_deal_value"] = stats["total_pipeline_value"] / len(deals)
        
        return stats
    
    def get_agent_performance(
        self,
        organization_id: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get agent performance metrics
        
        Returns:
            {
                total_deals: count,
                closed_deals: count,
                close_rate: percentage,
                pipeline_value: total,
                average_deal_value: amount,
                average_days_to_close: days
            }
        """
        query = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id)
        )
        
        if agent_id:
            query = query.filter(Deal.agent_id == as_uuid(agent_id))
        
        deals = query.all()
        closed_deals = [d for d in deals if d.status == "won"]
        
        # Calculate metrics
        total_deals = len(deals)
        total_closed = len(closed_deals)
        close_rate = (total_closed / total_deals * 100) if total_deals > 0 else 0
        
        pipeline_value = sum(float(d.offer_price or d.proposed_price) for d in deals if d.is_active)
        avg_deal_value = pipeline_value / total_deals if total_deals > 0 else 0
        
        # Average days to close
        days_to_close = []
        for deal in closed_deals:
            if deal.created_at and deal.closed_at:
                days = (deal.closed_at - deal.created_at).days
                days_to_close.append(days)
        
        avg_days = sum(days_to_close) / len(days_to_close) if days_to_close else 0
        
        return {
            "total_deals": total_deals,
            "closed_deals": total_closed,
            "close_rate": round(close_rate, 2),
            "pipeline_value": round(pipeline_value, 2),
            "average_deal_value": round(avg_deal_value, 2),
            "average_days_to_close": int(avg_days),
        }
    
    def forecast_revenue(
        self,
        organization_id: str,
        commission_rate: float = 0.05,
        close_probability: Dict[str, float] = None,
    ) -> Dict[str, float]:
        """
        Forecast expected revenue based on active deals
        
        Args:
            organization_id: Organization UUID
            commission_rate: Commission percentage
            close_probability: Stage-to-close probability mapping
                {"lead": 0.1, "offer": 0.4, "negotiation": 0.6, ...}
        
        Returns:
            {
                best_case: all deals close,
                worst_case: no deals close,
                probable: based on stage probabilities
            }
        """
        if close_probability is None:
            # Default probabilities by stage
            close_probability = {
                "lead": 0.10,
                "offer": 0.25,
                "negotiation": 0.50,
                "inspection": 0.70,
                "appraisal": 0.85,
                "closed": 1.00,
            }
        
        deals = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id),
            Deal.is_active == True,
        ).all()
        
        best_case = 0.0
        worst_case = 0.0
        probable = 0.0
        
        for deal in deals:
            sale_price = float(deal.offer_price or deal.proposed_price)
            commission = sale_price * commission_rate
            
            best_case += commission
            
            stage_prob = close_probability.get(deal.stage, 0.0)
            probable += commission * stage_prob
        
        return {
            "best_case": round(best_case, 2),
            "worst_case": round(worst_case, 2),
            "probable": round(probable, 2),
        }
    
    # ========================================================================
    # Delete & Archive
    # ========================================================================
    
    def archive_deal(
        self,
        deal_id: str,
        organization_id: str,
        user_id: str,
        reason: Optional[str] = None,
    ) -> Deal:
        """Archive deal"""
        deal = self.get_deal(deal_id, organization_id)
        
        if not deal:
            raise ValueError("Deal not found")
        
        deal.status = "inactive"
        deal.is_active = False
        self.db.commit()
        self.db.refresh(deal)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="deal_archived",
            entity_type="deal",
            entity_id=deal_id,
            new_values={"reason": reason or "no reason provided"},
        )
        
        return deal
    
    # ========================================================================
    # Statistics
    # ========================================================================
    
    def get_deal_stats(self, organization_id: str) -> Dict[str, Any]:
        """Get deal statistics for organization"""
        total = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id)
        ).count()
        
        active = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id),
            Deal.is_active == True,
        ).count()
        
        won = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id),
            Deal.status == "won",
        ).count()
        
        lost = self.db.query(Deal).filter(
            Deal.organization_id == as_uuid(organization_id),
            Deal.status == "lost",
        ).count()
        
        return {
            "total_deals": total,
            "active_deals": active,
            "won_deals": won,
            "lost_deals": lost,
            "win_rate": (won / total * 100) if total > 0 else 0,
            "active_percentage": (active / total * 100) if total > 0 else 0,
        }
    
    # ========================================================================
    # Private Methods
    # ========================================================================
    
    def _log_audit(
        self,
        organization_id: str,
        user_id: Optional[str],
        action: str,
        entity_type: str = "deal",
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
