"""
Call Logging Service
Business logic for call tracking, transcription, and analysis
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
import uuid
from models import as_uuid
import json

from models import (
    CallLog, Client, Deal, User, AuditLog, Organization
)

class CallLogService:
    """Service for call logging, transcription, and analysis"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ========================================================================
    # Create & Log Calls
    # ========================================================================
    
    def log_call(
        self,
        organization_id: str,
        agent_id: str,
        call_type: str,  # inbound, outbound, callback
        client_id: Optional[str] = None,
        property_id: Optional[str] = None,
        phone_number: Optional[str] = None,
        duration_seconds: int = 0,
        recording_url: Optional[str] = None,
        recording_duration_seconds: Optional[int] = None,
        transcript_language: Optional[str] = None,
    ) -> CallLog:
        """
        Log a call
        
        Args:
            organization_id: Organization UUID
            agent_id: Agent who took/made call
            call_type: inbound, outbound, or callback
            client_id: Client UUID (optional)
            property_id: Property UUID (optional)
            phone_number: Phone number involved
            duration_seconds: Call duration in seconds
            recording_url: URL to call recording
            recording_duration_seconds: Recording length in seconds
            transcript_language: Language code for transcription (e.g., 'en-US')
        
        Returns:
            Created CallLog object
        """
        call_log = CallLog(
            organization_id=as_uuid(organization_id),
            agent_id=as_uuid(agent_id),
            client_id=as_uuid(client_id) if client_id else None,
            property_id=as_uuid(property_id) if property_id else None,
            call_type=call_type,
            phone_number=phone_number,
            duration_seconds=duration_seconds,
            recording_url=recording_url,
            recording_duration_seconds=recording_duration_seconds,
            transcript_language=transcript_language,
        )
        
        self.db.add(call_log)
        self.db.commit()
        self.db.refresh(call_log)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=agent_id,
            action="call_logged",
            entity_type="call",
            entity_id=str(call_log.id),
            new_values={
                "call_type": call_type,
                "duration": duration_seconds,
                "client_id": client_id,
                "property_id": property_id,
            },
        )
        
        return call_log
    
    # ========================================================================
    # Read & Retrieve Calls
    # ========================================================================
    
    def get_call(
        self,
        call_id: str,
        organization_id: Optional[str] = None
    ) -> Optional[CallLog]:
        """Get call by ID"""
        query = self.db.query(CallLog).filter(
            CallLog.id == as_uuid(call_id)
        )
        
        if organization_id:
            query = query.filter(CallLog.organization_id == as_uuid(organization_id))
        
        return query.first()
    
    def list_calls(
        self,
        organization_id: str,
        skip: int = 0,
        limit: int = 50,
        agent_id: Optional[str] = None,
        client_id: Optional[str] = None,
        property_id: Optional[str] = None,
        call_type: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[List[CallLog], int]:
        """
        List calls with filters
        
        Args:
            organization_id: Organization UUID
            skip: Number to skip
            limit: Number to return
            agent_id: Filter by agent
            client_id: Filter by client
            property_id: Filter by property
            call_type: inbound, outbound, callback
            date_from: Start date
            date_to: End date
            sort_by: created_at, duration_seconds
            sort_order: asc or desc
        
        Returns:
            Tuple of (calls list, total count)
        """
        query = self.db.query(CallLog).filter(
            CallLog.organization_id == as_uuid(organization_id)
        )
        
        # Apply filters
        if agent_id:
            query = query.filter(CallLog.agent_id == as_uuid(agent_id))
        
        if client_id:
            query = query.filter(CallLog.client_id == as_uuid(client_id))
        
        if property_id:
            query = query.filter(CallLog.property_id == as_uuid(property_id))
        
        if call_type:
            query = query.filter(CallLog.call_type == call_type)
        
        if date_from:
            query = query.filter(CallLog.created_at >= date_from)
        
        if date_to:
            query = query.filter(CallLog.created_at <= date_to)
        
        # Count total
        total = query.count()
        
        # Sort
        if sort_by == "duration_seconds":
            query = query.order_by(
                CallLog.duration_seconds.desc() if sort_order == "desc" else CallLog.duration_seconds.asc()
            )
        else:  # created_at
            query = query.order_by(
                CallLog.created_at.desc() if sort_order == "desc" else CallLog.created_at.asc()
            )
        
        # Pagination
        calls = query.offset(skip).limit(limit).all()
        
        return calls, total
    
    # ========================================================================
    # Transcription & Processing
    # ========================================================================
    
    def add_transcript(
        self,
        call_id: str,
        organization_id: str,
        transcript: str,
        transcript_provider: str = "manual",  # manual, aws_transcribe, google_cloud, azure
    ) -> CallLog:
        """
        Add or update call transcript
        
        Args:
            call_id: Call UUID
            organization_id: Organization UUID
            transcript: Full transcript text
            transcript_provider: Source of transcript
        
        Returns:
            Updated CallLog object
        """
        call = self.get_call(call_id, organization_id)
        
        if not call:
            raise ValueError("Call not found")
        
        call.transcript = transcript
        call.transcript_provider = transcript_provider
        call.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(call)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=None,
            action="transcript_added",
            entity_type="call",
            entity_id=call_id,
            new_values={"transcript_provider": transcript_provider},
        )
        
        return call
    
    def add_summary(
        self,
        call_id: str,
        organization_id: str,
        summary: str,
        key_topics: Optional[List[str]] = None,
        sentiment_label: Optional[str] = None,  # positive, neutral, negative
        sentiment_score: Optional[float] = None,  # 0.0 to 1.0
        call_quality: Optional[str] = None,  # poor, fair, good, excellent
    ) -> CallLog:
        """
        Add AI-generated summary of call
        
        Args:
            call_id: Call UUID
            organization_id: Organization UUID
            summary: Summary text
            key_topics: List of key discussion topics
            sentiment_label: Overall sentiment (positive, neutral, negative)
            sentiment_score: Sentiment score from 0-1
            call_quality: Quality rating (poor, fair, good, excellent)
        
        Returns:
            Updated CallLog object
        """
        call = self.get_call(call_id, organization_id)
        
        if not call:
            raise ValueError("Call not found")
        
        call.ai_summary = summary
        call.key_topics = key_topics or []
        call.sentiment_label = sentiment_label
        call.sentiment_score = sentiment_score
        call.call_quality = call_quality
        call.processed_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(call)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=None,
            action="summary_added",
            entity_type="call",
            entity_id=call_id,
            new_values={
                "sentiment_label": sentiment_label,
                "sentiment_score": sentiment_score,
                "call_quality": call_quality,
            },
        )
        
        return call
    
    def extract_action_items(
        self,
        call_id: str,
        organization_id: str,
        action_items: List[Dict[str, Any]],
    ) -> CallLog:
        """
        Extract and store action items from call
        
        Args:
            call_id: Call UUID
            organization_id: Organization UUID
            action_items: List of {description, assigned_to, due_date, priority}
        
        Returns:
            Updated CallLog object
        """
        call = self.get_call(call_id, organization_id)
        
        if not call:
            raise ValueError("Call not found")
        
        call.action_items = action_items
        call.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(call)
        
        return call
    
    # ========================================================================
    # Call Analytics
    # ========================================================================
    
    def get_call_stats(
        self,
        organization_id: str,
        agent_id: Optional[str] = None,
        date_from: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get call statistics
        
        Args:
            organization_id: Organization UUID
            agent_id: Optional specific agent
            date_from: Optional start date (default: last 30 days)
        
        Returns:
            {
                total_calls: count,
                total_duration: seconds,
                average_duration: seconds,
                by_type: {inbound: count, outbound: count, callback: count},
                average_call_duration: seconds,
                calls_with_transcript: count,
                calls_with_summary: count,
                calls_processed: count,
            }
        """
        if not date_from:
            date_from = datetime.utcnow() - timedelta(days=30)
        
        query = self.db.query(CallLog).filter(
            CallLog.organization_id == as_uuid(organization_id),
            CallLog.created_at >= date_from,
        )
        
        if agent_id:
            query = query.filter(CallLog.agent_id == as_uuid(agent_id))
        
        calls = query.all()
        
        if not calls:
            return {
                "total_calls": 0,
                "total_duration": 0,
                "average_duration": 0,
                "by_type": {},
                "average_call_duration": 0,
                "calls_with_transcript": 0,
                "calls_with_summary": 0,
                "calls_processed": 0,
            }
        
        # Calculate stats
        total_calls = len(calls)
        total_duration = sum(c.duration_seconds for c in calls)
        average_duration = total_duration // total_calls if total_calls > 0 else 0
        
        # By type
        by_type = {}
        for call in calls:
            by_type[call.call_type] = by_type.get(call.call_type, 0) + 1
        
        # Transcript & summary counts
        calls_with_transcript = sum(1 for c in calls if c.transcript)
        calls_with_summary = sum(1 for c in calls if c.ai_summary)
        calls_processed = sum(1 for c in calls if c.processed_at is not None)
        
        return {
            "total_calls": total_calls,
            "total_duration": total_duration,
            "average_duration": average_duration,
            "by_type": by_type,
            "average_call_duration": average_duration,
            "calls_with_transcript": calls_with_transcript,
            "calls_with_summary": calls_with_summary,
            "calls_processed": calls_processed,
        }
    
    def get_agent_call_stats(self, organization_id: str, agent_id: str) -> Dict[str, Any]:
        """Get call statistics for specific agent"""
        return self.get_call_stats(organization_id, agent_id)
    
    def get_client_call_history(self, client_id: str, limit: int = 50) -> List[CallLog]:
        """Get all calls for a specific client"""
        return self.db.query(CallLog).filter(
            CallLog.client_id == as_uuid(client_id)
        ).order_by(CallLog.created_at.desc()).limit(limit).all()
    
    def get_property_call_history(self, property_id: str, limit: int = 50) -> List[CallLog]:
        """Get all calls related to a specific property"""
        return self.db.query(CallLog).filter(
            CallLog.property_id == as_uuid(property_id)
        ).order_by(CallLog.created_at.desc()).limit(limit).all()
    
    # ========================================================================
    # Call Quality Metrics
    # ========================================================================
    
    def get_call_quality_score(self, call_id: str) -> Optional[float]:
        """
        Calculate call quality score (0-100)
        
        Based on:
        - Duration (calls too short are low quality)
        - Transcript availability
        - Summary availability
        - Sentiment (positive sentiment = higher quality)
        - Action items (follow-up indicates quality)
        """
        call = self.get_call(call_id)
        
        if not call:
            return None
        
        score = 50.0  # Base score
        
        # Duration scoring (target: 2-5 minutes = 120-300 seconds)
        if call.duration_seconds < 60:
            score -= 20  # Too short
        elif call.duration_seconds > 1800:
            score -= 10  # Too long
        else:
            score += 15  # Good duration
        
        # Transcript
        if call.transcript:
            score += 10
        
        # Summary (ai_summary)
        if call.ai_summary:
            score += 10
        
        # Sentiment
        if call.sentiment_label == "positive":
            score += 10
        elif call.sentiment_label == "negative":
            score -= 10
        
        # Action items
        if call.action_items:
            score += 5
        
        return min(100.0, max(0.0, score))
    
    # ========================================================================
    # Update & Delete
    # ========================================================================
    
    def update_call_notes(
        self,
        call_id: str,
        organization_id: str,
        notes: str,
    ) -> CallLog:
        """Update call notes"""
        call = self.get_call(call_id, organization_id)
        
        if not call:
            raise ValueError("Call not found")
        
        call.notes = notes
        call.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(call)
        
        return call
    
    def delete_call(
        self,
        call_id: str,
        organization_id: str,
        user_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Delete call (soft delete)"""
        call = self.get_call(call_id, organization_id)
        
        if not call:
            raise ValueError("Call not found")
        
        call.deleted_at = datetime.utcnow()
        self.db.commit()
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=user_id,
            action="call_deleted",
            entity_type="call",
            entity_id=call_id,
            new_values={"reason": reason or "no reason"},
        )
        
        return True
    
    # ========================================================================
    # Private Methods
    # ========================================================================
    
    def _log_audit(
        self,
        organization_id: str,
        user_id: Optional[str],
        action: str,
        entity_type: str = "call",
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
