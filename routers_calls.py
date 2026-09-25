"""
Call Logging Routes
REST API endpoints for call logging, transcription, and analysis
"""

from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import logging

from config import get_db
from models import CallLog, User, UserRole
from services_calls import CallLogService
from middleware_auth import require_role, get_current_user, UserContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["Call Logging"])

# ============================================================================
# Dependency: CallLogService
# ============================================================================

def get_call_service(db: Session = Depends(get_db)) -> CallLogService:
    """Get call service instance"""
    return CallLogService(db)

# ============================================================================
# Log a Call
# ============================================================================

@router.post("/log")
async def log_call(
    call_type: str,
    agent_id: str,
    duration_seconds: int,
    organization_id: str,
    client_id: Optional[str] = None,
    property_id: Optional[str] = None,
    phone_number: Optional[str] = None,
    recording_url: Optional[str] = None,
    recording_duration_seconds: Optional[int] = None,
    transcript_language: Optional[str] = None,
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Log a call
    
    **Authorization:** Agent or Admin
    
    Args:
        call_type: inbound, outbound, or callback
        agent_id: Agent UUID
        duration_seconds: Call duration in seconds
        organization_id: Organization UUID
        client_id: Optional client UUID
        property_id: Optional property UUID
        phone_number: Optional phone number
        recording_url: Optional recording URL
        recording_duration_seconds: Optional recording length
        transcript_language: Optional language code (e.g., en-US)
    
    Returns:
        Created call object
    """
    try:
        # Authorization check
        if user_context.role == UserRole.AGENT and user_context.user_id != agent_id:
            raise HTTPException(status_code=403, detail="Cannot log calls for other agents")
        
        # Validate call type
        valid_types = ["inbound", "outbound", "callback"]
        if call_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid call_type. Must be one of: {', '.join(valid_types)}"
            )
        
        call = service.log_call(
            organization_id=organization_id,
            agent_id=agent_id,
            call_type=call_type,
            client_id=client_id,
            property_id=property_id,
            phone_number=phone_number,
            duration_seconds=duration_seconds,
            recording_url=recording_url,
            recording_duration_seconds=recording_duration_seconds,
            transcript_language=transcript_language,
        )
        
        return {
            "id": str(call.id),
            "call_type": call.call_type,
            "duration_seconds": call.duration_seconds,
            "client_id": str(call.client_id) if call.client_id else None,
            "created_at": call.created_at.isoformat(),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error logging call: {e}")
        raise HTTPException(status_code=500, detail="Failed to log call")

# ============================================================================
# List Calls
# ============================================================================

@router.get("")
async def list_calls(
    organization_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    agent_id: Optional[str] = None,
    client_id: Optional[str] = None,
    property_id: Optional[str] = None,
    call_type: Optional[str] = None,
    date_from: Optional[str] = None,  # ISO format
    date_to: Optional[str] = None,  # ISO format
    sort_by: str = Query("created_at", regex="^(created_at|duration_seconds)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    List calls with optional filters
    
    **Authorization:** Agent or Admin
    
    Query Parameters:
        - skip: Number of records to skip (default: 0)
        - limit: Number of records to return (default: 50, max: 500)
        - agent_id: Filter by agent UUID
        - client_id: Filter by client UUID
        - property_id: Filter by property UUID
        - call_type: Filter by type (inbound, outbound, callback)
        - date_from: Filter from date (ISO format, e.g., 2026-09-25)
        - date_to: Filter to date (ISO format)
        - sort_by: Sort field (created_at or duration_seconds)
        - sort_order: Sort direction (asc or desc)
    
    Returns:
        Paginated list of calls
    """
    try:
        # Authorization check: agents can only see their own calls
        if user_context.role == UserRole.AGENT and agent_id and user_context.user_id != agent_id:
            raise HTTPException(status_code=403, detail="Cannot view other agents' calls")
        
        # Parse dates
        dt_from = None
        dt_to = None
        
        if date_from:
            try:
                dt_from = datetime.fromisoformat(date_from)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_from format (use ISO format)")
        
        if date_to:
            try:
                dt_to = datetime.fromisoformat(date_to)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date_to format (use ISO format)")
        
        # Auto-filter for agents
        if user_context.role == UserRole.AGENT:
            agent_id = user_context.user_id
        
        calls, total = service.list_calls(
            organization_id=organization_id,
            skip=skip,
            limit=limit,
            agent_id=agent_id,
            client_id=client_id,
            property_id=property_id,
            call_type=call_type,
            date_from=dt_from,
            date_to=dt_to,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "data": [
                {
                    "id": str(c.id),
                    "call_type": c.call_type,
                    "client_id": str(c.client_id) if c.client_id else None,
                    "property_id": str(c.property_id) if c.property_id else None,
                    "agent_id": str(c.agent_id),
                    "phone_number": c.phone_number,
                    "duration_seconds": c.duration_seconds,
                    "has_transcript": bool(c.transcript),
                    "has_summary": bool(c.ai_summary),
                    "sentiment": c.sentiment_label,
                    "call_quality": c.call_quality,
                    "created_at": c.created_at.isoformat(),
                }
                for c in calls
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing calls: {e}")
        raise HTTPException(status_code=500, detail="Failed to list calls")

# ============================================================================
# Get Call Details
# ============================================================================

@router.get("/{call_id}")
async def get_call(
    call_id: str,
    organization_id: str,
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Get call details including transcript and summary
    
    **Authorization:** Agent (own calls) or Admin
    """
    try:
        call = service.get_call(call_id, organization_id)
        
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        
        # Authorization check
        if user_context.role == UserRole.AGENT and str(call.agent_id) != user_context.user_id:
            raise HTTPException(status_code=403, detail="Cannot view other agents' calls")
        
        return {
            "id": str(call.id),
            "organization_id": str(call.organization_id),
            "agent_id": str(call.agent_id),
            "client_id": str(call.client_id) if call.client_id else None,
            "property_id": str(call.property_id) if call.property_id else None,
            "call_type": call.call_type,
            "phone_number": call.phone_number,
            "duration_seconds": call.duration_seconds,
            "recording_url": call.recording_url,
            "recording_duration_seconds": call.recording_duration_seconds,
            "transcript": call.transcript,
            "transcript_language": call.transcript_language,
            "summary": call.ai_summary,
            "key_topics": call.key_topics or [],
            "action_items": call.action_items or [],
            "sentiment_score": float(call.sentiment_score) if call.sentiment_score else None,
            "sentiment_label": call.sentiment_label,
            "call_quality": call.call_quality,
            "created_at": call.created_at.isoformat(),
            "processed_at": call.processed_at.isoformat() if call.processed_at else None,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting call: {e}")
        raise HTTPException(status_code=500, detail="Failed to get call")

# ============================================================================
# Add Transcript
# ============================================================================

@router.post("/{call_id}/transcript")
async def add_transcript(
    call_id: str,
    organization_id: str,
    transcript: str,
    transcript_provider: str = "manual",
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Add or update call transcript
    
    **Authorization:** Admin or call's agent
    
    Args:
        call_id: Call UUID
        organization_id: Organization UUID
        transcript: Full transcript text
        transcript_provider: Source (manual, aws_transcribe, google_cloud, azure)
    
    Returns:
        Updated call object
    """
    try:
        call = service.get_call(call_id, organization_id)
        
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        
        # Authorization check
        if user_context.role == UserRole.AGENT and str(call.agent_id) != user_context.user_id:
            raise HTTPException(status_code=403, detail="Cannot update other agents' calls")
        
        # Validate provider
        valid_providers = ["manual", "aws_transcribe", "google_cloud", "azure"]
        if transcript_provider not in valid_providers:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider. Must be one of: {', '.join(valid_providers)}"
            )
        
        updated_call = service.add_transcript(
            call_id=call_id,
            organization_id=organization_id,
            transcript=transcript,
            transcript_provider=transcript_provider,
        )
        
        return {
            "id": str(updated_call.id),
            "transcript_provider": updated_call.transcript_provider,
            "transcript_language": updated_call.transcript_language,
            "updated_at": updated_call.updated_at.isoformat() if updated_call.updated_at else None,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding transcript: {e}")
        raise HTTPException(status_code=500, detail="Failed to add transcript")

# ============================================================================
# Add Summary
# ============================================================================

@router.post("/{call_id}/summary")
async def add_summary(
    call_id: str,
    organization_id: str,
    summary: str,
    key_topics: Optional[List[str]] = None,
    sentiment_label: Optional[str] = None,
    sentiment_score: Optional[float] = None,
    call_quality: Optional[str] = None,
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Add AI-generated summary to call
    
    **Authorization:** Admin or call's agent
    
    Args:
        call_id: Call UUID
        organization_id: Organization UUID
        summary: Summary text
        key_topics: List of key discussion topics
        sentiment_label: positive, neutral, or negative
        sentiment_score: Score from 0.0 to 1.0
        call_quality: poor, fair, good, or excellent
    
    Returns:
        Updated call object
    """
    try:
        call = service.get_call(call_id, organization_id)
        
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        
        # Authorization check
        if user_context.role == UserRole.AGENT and str(call.agent_id) != user_context.user_id:
            raise HTTPException(status_code=403, detail="Cannot update other agents' calls")
        
        # Validate sentiment_score
        if sentiment_score is not None and not (0.0 <= sentiment_score <= 1.0):
            raise HTTPException(status_code=400, detail="sentiment_score must be between 0.0 and 1.0")
        
        # Validate call_quality
        if call_quality and call_quality not in ["poor", "fair", "good", "excellent"]:
            raise HTTPException(
                status_code=400,
                detail="call_quality must be one of: poor, fair, good, excellent"
            )
        
        updated_call = service.add_summary(
            call_id=call_id,
            organization_id=organization_id,
            summary=summary,
            key_topics=key_topics,
            sentiment_label=sentiment_label,
            sentiment_score=sentiment_score,
            call_quality=call_quality,
        )
        
        return {
            "id": str(updated_call.id),
            "summary": updated_call.ai_summary,
            "key_topics": updated_call.key_topics or [],
            "sentiment_label": updated_call.sentiment_label,
            "sentiment_score": float(updated_call.sentiment_score) if updated_call.sentiment_score else None,
            "call_quality": updated_call.call_quality,
            "processed_at": updated_call.processed_at.isoformat() if updated_call.processed_at else None,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to add summary")

# ============================================================================
# Add Action Items
# ============================================================================

@router.post("/{call_id}/action-items")
async def add_action_items(
    call_id: str,
    organization_id: str,
    action_items: List[str],
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Add action items to a call
    
    **Authorization:** Admin or call's agent
    
    Args:
        call_id: Call UUID
        organization_id: Organization UUID
        action_items: List of action item descriptions
    
    Returns:
        Updated call object
    """
    try:
        call = service.get_call(call_id, organization_id)
        
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        
        # Authorization check
        if user_context.role == UserRole.AGENT and str(call.agent_id) != user_context.user_id:
            raise HTTPException(status_code=403, detail="Cannot update other agents' calls")
        
        updated_call = service.extract_action_items(
            call_id=call_id,
            organization_id=organization_id,
            action_items=action_items,
        )
        
        return {
            "id": str(updated_call.id),
            "action_items": updated_call.action_items or [],
            "updated_at": updated_call.updated_at.isoformat() if updated_call.updated_at else None,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding action items: {e}")
        raise HTTPException(status_code=500, detail="Failed to add action items")

# ============================================================================
# Call Statistics
# ============================================================================

@router.get("/admin/stats")
async def get_call_stats(
    organization_id: str,
    agent_id: Optional[str] = None,
    days: int = Query(30, ge=1, le=365),
    user_context: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Get call statistics (Admin only)
    
    **Authorization:** Admin
    
    Query Parameters:
        - agent_id: Optional agent UUID
        - days: Number of days to analyze (default: 30, max: 365)
    
    Returns:
        Call statistics including totals, averages, and breakdowns
    """
    try:
        date_from = datetime.utcnow() - timedelta(days=days)
        
        stats = service.get_call_stats(
            organization_id=organization_id,
            agent_id=agent_id,
            date_from=date_from,
        )
        
        return {
            "period_days": days,
            "date_from": date_from.isoformat(),
            "date_to": datetime.utcnow().isoformat(),
            "stats": stats,
        }
    
    except Exception as e:
        logger.error(f"Error getting call stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get call statistics")

# ============================================================================
# Client Call History
# ============================================================================

@router.get("/client/{client_id}/history")
async def get_client_calls(
    client_id: str,
    organization_id: str,
    limit: int = Query(50, ge=1, le=500),
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Get all calls for a specific client
    
    **Authorization:** Agent (if client assigned) or Admin
    """
    try:
        calls = service.get_client_call_history(client_id, limit)
        
        return {
            "client_id": client_id,
            "total": len(calls),
            "data": [
                {
                    "id": str(c.id),
                    "call_type": c.call_type,
                    "duration_seconds": c.duration_seconds,
                    "agent_id": str(c.agent_id),
                    "sentiment": c.sentiment_label,
                    "has_summary": bool(c.ai_summary),
                    "created_at": c.created_at.isoformat(),
                }
                for c in calls
            ]
        }
    
    except Exception as e:
        logger.error(f"Error getting client calls: {e}")
        raise HTTPException(status_code=500, detail="Failed to get client call history")

# ============================================================================
# Property Call History
# ============================================================================

@router.get("/property/{property_id}/history")
async def get_property_calls(
    property_id: str,
    organization_id: str,
    limit: int = Query(50, ge=1, le=500),
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Get all calls related to a specific property
    
    **Authorization:** Agent or Admin
    """
    try:
        calls = service.get_property_call_history(property_id, limit)
        
        return {
            "property_id": property_id,
            "total": len(calls),
            "data": [
                {
                    "id": str(c.id),
                    "call_type": c.call_type,
                    "client_id": str(c.client_id) if c.client_id else None,
                    "duration_seconds": c.duration_seconds,
                    "agent_id": str(c.agent_id),
                    "sentiment": c.sentiment_label,
                    "created_at": c.created_at.isoformat(),
                }
                for c in calls
            ]
        }
    
    except Exception as e:
        logger.error(f"Error getting property calls: {e}")
        raise HTTPException(status_code=500, detail="Failed to get property call history")

# ============================================================================
# Delete Call
# ============================================================================

@router.delete("/{call_id}")
async def delete_call(
    call_id: str,
    organization_id: str,
    reason: Optional[str] = None,
    user_context: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: CallLogService = Depends(get_call_service),
) -> dict:
    """
    Delete a call (soft delete)
    
    **Authorization:** Admin only
    
    Args:
        call_id: Call UUID
        organization_id: Organization UUID
        reason: Optional deletion reason
    
    Returns:
        Success response
    """
    try:
        success = service.delete_call(
            call_id=call_id,
            organization_id=organization_id,
            user_id=user_context.user_id,
            reason=reason,
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Call not found")
        
        return {"success": True, "call_id": call_id}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting call: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete call")
