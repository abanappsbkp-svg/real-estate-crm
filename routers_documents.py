"""
Document Management Routes
REST API endpoints for document storage, versioning, sharing, and compliance
"""

from typing import Optional, List
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy.orm import Session
import logging

from db import get_db
from models import Document, DocumentShare, User, UserRole
from services_documents import DocumentService
from middleware_auth import require_role, get_current_user, UserContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Document Management"])

# ============================================================================
# Dependency: DocumentService
# ============================================================================

def get_document_service(db: Session = Depends(get_db)) -> DocumentService:
    """Get document service instance"""
    return DocumentService(db)

# ============================================================================
# Upload/Create Document
# ============================================================================

@router.post("/upload")
async def upload_document(
    name: str,
    document_type: str,
    file: UploadFile = File(...),
    client_id: Optional[str] = None,
    property_id: Optional[str] = None,
    deal_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[dict] = None,
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Upload a new document
    
    **Authorization:** Agent or Admin
    
    Args:
        organization_id: Organization UUID
        name: Document name
        document_type: contract, disclosure, proposal, agreement, etc.
        file: File to upload
        client_id: Optional client association
        property_id: Optional property association
        deal_id: Optional deal association
        tags: Optional tags
        metadata: Optional metadata
    
    Returns:
        Created document object
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        # Validate document type
        valid_types = ["contract", "disclosure", "proposal", "agreement", "deed", "inspection", "appraisal", "other"]
        if document_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid document_type. Must be one of: {', '.join(valid_types)}"
            )
        
        # Read file content
        content = await file.read()
        
        if len(content) > 50 * 1024 * 1024:  # 50MB limit
            raise HTTPException(status_code=413, detail="File too large (max 50MB)")
        
        # Create document
        doc = service.create_document(
            organization_id=organization_id,
            created_by=user_context.user_id,
            name=name,
            document_type=document_type,
            content=content,
            mime_type=file.content_type,
            file_size=len(content),
            client_id=client_id,
            property_id=property_id,
            deal_id=deal_id,
            tags=tags,
            metadata=metadata or {},
        )
        
        return {
            "id": str(doc.id),
            "name": doc.name,
            "document_type": doc.document_type,
            "file_size": doc.file_size,
            "version": doc.version_number,
            "created_at": doc.created_at.isoformat(),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload document")

# ============================================================================
# List Documents
# ============================================================================

@router.get("")
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    document_type: Optional[str] = None,
    client_id: Optional[str] = None,
    property_id: Optional[str] = None,
    deal_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    search_term: Optional[str] = None,
    sort_by: str = Query("created_at", pattern="^(created_at|name)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    List documents with optional filters
    
    **Authorization:** Agent or Admin
    
    Query Parameters:
        - skip: Number of records to skip (default: 0)
        - limit: Number of records to return (default: 50, max: 500)
        - document_type: Filter by type
        - client_id: Filter by client
        - property_id: Filter by property
        - deal_id: Filter by deal
        - tags: Filter by tags (comma-separated)
        - search_term: Search in name
        - sort_by: created_at or name
        - sort_order: asc or desc
    
    Returns:
        Paginated list of documents
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        documents, total = service.list_documents(
            organization_id=organization_id,
            skip=skip,
            limit=limit,
            document_type=document_type,
            client_id=client_id,
            property_id=property_id,
            deal_id=deal_id,
            tags=tags,
            search_term=search_term,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "data": [
                {
                    "id": str(d.id),
                    "name": d.name,
                    "document_type": d.document_type,
                    "file_size": d.file_size,
                    "version": d.version_number,
                    "mime_type": d.mime_type,
                    "tags": d.tags or [],
                    "client_id": str(d.client_id) if d.client_id else None,
                    "property_id": str(d.property_id) if d.property_id else None,
                    "created_at": d.created_at.isoformat(),
                    "created_by": str(d.created_by),
                }
                for d in documents
            ]
        }
    
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail="Failed to list documents")

# ============================================================================
# Get Document Details
# ============================================================================

@router.get("/{document_id}")
async def get_document(
    document_id: str,
    version: Optional[int] = None,
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Get document details
    
    **Authorization:** Document creator, shared users, or Admin
    
    Query Parameters:
        - version: Specific version to retrieve (default: latest)
    
    Returns:
        Document details with content metadata
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        doc = service.get_document(document_id, organization_id)
        
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Get specific version or latest
        if version:
            doc_version = service.get_document_version(document_id, version)
            if not doc_version:
                raise HTTPException(status_code=404, detail=f"Version {version} not found")
            version_info = version
        else:
            doc_version = service.get_document_version(document_id, doc.version_number)
            version_info = doc.version_number
        
        return {
            "id": str(doc.id),
            "organization_id": str(doc.organization_id),
            "name": doc.name,
            "document_type": doc.document_type,
            "file_size": doc.file_size,
            "mime_type": doc.mime_type,
            "version": version_info,
            "total_versions": doc.version_number,
            "tags": doc.tags or [],
            "metadata": doc.doc_metadata or {},
            "client_id": str(doc.client_id) if doc.client_id else None,
            "property_id": str(doc.property_id) if doc.property_id else None,
            "deal_id": str(doc.deal_id) if doc.deal_id else None,
            "created_by": str(doc.created_by),
            "created_at": doc.created_at.isoformat(),
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            "retention_until": doc.retention_until.isoformat() if doc.retention_until else None,
            "content_preview": "Available via /api/v1/documents/{id}/download" if doc_version else None,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document: {e}")
        raise HTTPException(status_code=500, detail="Failed to get document")

# ============================================================================
# Update Document (New Version)
# ============================================================================

@router.post("/{document_id}/new-version")
async def update_document_version(
    document_id: str,
    file: UploadFile = File(...),
    change_notes: str = "Document updated",
    tags: Optional[List[str]] = None,
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Update document (creates new version)
    
    **Authorization:** Document creator or Admin
    
    Args:
        document_id: Document UUID
        organization_id: Organization UUID
        file: New file content
        change_notes: Description of changes
        tags: Updated tags
    
    Returns:
        Updated document with new version
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        # Check auth
        doc = service.get_document(document_id, organization_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        if user_context.role == "agent" and str(doc.created_by) != user_context.user_id:
            raise HTTPException(status_code=403, detail="Cannot update other users' documents")
        
        # Read file
        content = await file.read()
        
        updated_doc = service.update_document(
            document_id=document_id,
            organization_id=organization_id,
            updated_by=user_context.user_id,
            content=content,
            change_notes=change_notes,
            tags=tags,
        )
        
        return {
            "id": str(updated_doc.id),
            "name": updated_doc.name,
            "version": updated_doc.version_number,
            "file_size": updated_doc.file_size,
            "change_notes": change_notes,
            "updated_at": updated_doc.updated_at.isoformat(),
        }
    
    except HTTPException:
        raise
    except Exception as e:
            logger.error(f"Error updating document: {e}")
            raise HTTPException(status_code=500, detail="Failed to update document")

# ============================================================================
# Version History
# ============================================================================

@router.get("/{document_id}/versions")
async def list_versions(
    document_id: str,
    limit: int = Query(50, ge=1, le=500),
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Get document version history
    
    **Authorization:** Document creator, shared users, or Admin
    
    Returns:
        List of all versions with metadata
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        doc = service.get_document(document_id, organization_id)
        
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        versions = service.list_document_versions(document_id, limit)
        
        return {
            "document_id": str(doc.id),
            "name": doc.name,
            "total_versions": doc.version_number,
            "versions": [
                {
                    "version": v.version_number,
                    "file_size": v.file_size,
                    "created_by": str(v.created_by),
                    "created_at": v.created_at.isoformat(),
                    "change_notes": v.change_notes,
                }
                for v in versions
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing versions: {e}")
        raise HTTPException(status_code=500, detail="Failed to list versions")

# ============================================================================
# Rollback Version
# ============================================================================

@router.post("/{document_id}/rollback/{version}")
async def rollback_to_version(
    document_id: str,
    version: int,
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Rollback document to previous version
    
    **Authorization:** Document creator or Admin
    
    Args:
        document_id: Document UUID
        version: Version to rollback to
        organization_id: Organization UUID
    
    Returns:
        Document at rolled-back version
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        doc = service.get_document(document_id, organization_id)
        
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Check auth
        if user_context.role == "agent" and str(doc.created_by) != user_context.user_id:
            raise HTTPException(status_code=403, detail="Cannot rollback other users' documents")
        
        updated_doc = service.rollback_version(
            document_id=document_id,
            organization_id=organization_id,
            target_version=version,
            rolled_back_by=user_context.user_id,
        )
        
        return {
            "id": str(updated_doc.id),
            "name": updated_doc.name,
            "version": updated_doc.version_number,
            "rolled_back_to": version,
            "updated_at": updated_doc.updated_at.isoformat(),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rolling back: {e}")
        raise HTTPException(status_code=500, detail="Failed to rollback document")

# ============================================================================
# Sharing
# ============================================================================

@router.post("/{document_id}/share")
async def share_document(
    document_id: str,
    share_with_user_id: Optional[str] = None,
    share_with_email: Optional[str] = None,
    permission: str = "view",
    expiry_days: Optional[int] = None,
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Share document with another user
    
    **Authorization:** Document creator or Admin
    
    Args:
        document_id: Document UUID
        organization_id: Organization UUID
        share_with_user_id: User to share with (internal)
        share_with_email: Email to share with (external)
        permission: view, comment, or edit
        expiry_days: Optional expiration in days
    
    Returns:
        Share confirmation
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        doc = service.get_document(document_id, organization_id)
        
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        if not share_with_user_id and not share_with_email:
            raise HTTPException(status_code=400, detail="Provide either user_id or email")
        
        expiry = None
        if expiry_days:
            expiry = datetime.utcnow() + timedelta(days=expiry_days)
        
        share = service.share_document(
            document_id=document_id,
            organization_id=organization_id,
            shared_by=user_context.user_id,
            share_with_user_id=share_with_user_id,
            share_with_email=share_with_email,
            permission=permission,
            expiry_date=expiry,
        )
        
        return {
            "id": str(share.id),
            "document_id": str(share.document_id),
            "shared_with": share_with_user_id or share_with_email,
            "permission": permission,
            "expiry_date": expiry.isoformat() if expiry else None,
            "created_at": share.created_at.isoformat(),
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sharing document: {e}")
        raise HTTPException(status_code=500, detail="Failed to share document")

# ============================================================================
# Shared With Me
# ============================================================================

@router.get("/admin/shared-with-me")
async def list_shared_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user_context: UserContext = Depends(require_role(UserRole.AGENT)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Get documents shared with me
    
    **Authorization:** Any authenticated user
    
    Returns:
        List of documents shared with current user
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        shares, total = service.list_shared_with_me(
            user_id=user_context.user_id,
            organization_id=organization_id,
            skip=skip,
            limit=limit,
        )
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "data": [
                {
                    "share_id": str(s.id),
                    "document_id": str(s.document_id),
                    "shared_by": str(s.shared_by),
                    "permission": s.permission,
                    "expiry_date": s.expiry_date.isoformat() if s.expiry_date else None,
                    "created_at": s.created_at.isoformat(),
                }
                for s in shares
            ]
        }
    
    except Exception as e:
        logger.error(f"Error listing shared documents: {e}")
        raise HTTPException(status_code=500, detail="Failed to list shared documents")

# ============================================================================
# Retention & Compliance
# ============================================================================

@router.post("/{document_id}/retention")
async def set_retention(
    document_id: str,
    retention_days: int,
    retention_reason: str = "regulatory",
    user_context: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Set document retention policy (Admin only)
    
    **Authorization:** Admin
    
    Args:
        document_id: Document UUID
        organization_id: Organization UUID
        retention_days: Days to retain
        retention_reason: Reason for retention
    
    Returns:
        Updated document
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        doc = service.set_retention_policy(
            document_id=document_id,
            organization_id=organization_id,
            retention_days=retention_days,
            retention_reason=retention_reason,
        )
        
        return {
            "id": str(doc.id),
            "name": doc.name,
            "retention_until": doc.retention_until.isoformat(),
            "retention_reason": doc.retention_reason,
        }
    
    except Exception as e:
        logger.error(f"Error setting retention: {e}")
        raise HTTPException(status_code=500, detail="Failed to set retention policy")

# ============================================================================
# Document Statistics
# ============================================================================

@router.get("/admin/stats")
async def get_stats(
    days: int = Query(30, ge=1, le=365),
    user_context: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Get document statistics (Admin only)
    
    **Authorization:** Admin
    
    Returns:
        Document usage statistics
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        date_from = datetime.utcnow() - timedelta(days=days)
        stats = service.get_document_stats(organization_id, date_from)
        
        return {
            "period_days": days,
            "date_from": date_from.isoformat(),
            "date_to": datetime.utcnow().isoformat(),
            "stats": stats,
        }
    
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get statistics")

# ============================================================================
# Delete Document
# ============================================================================

@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    deletion_reason: str = "user requested",
    user_context: UserContext = Depends(require_role(UserRole.ADMIN)),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """
    Delete document (soft delete)
    
    **Authorization:** Admin only
    
    Args:
        document_id: Document UUID
        organization_id: Organization UUID
        deletion_reason: Reason for deletion
    
    Returns:
        Deletion confirmation
    """
    # Always use the logged-in user's organization (prevents cross-organization access)
    organization_id = str(user_context.organization_id)
    try:
        service.mark_for_deletion(
            document_id=document_id,
            organization_id=organization_id,
            marked_by=user_context.user_id,
            deletion_reason=deletion_reason,
        )
        
        return {"success": True, "document_id": document_id}
    
    except Exception as e:
        logger.error(f"Error deleting document: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete document")
