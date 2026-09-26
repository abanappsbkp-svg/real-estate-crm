"""
Document Management Service
Business logic for document storage, versioning, sharing, and compliance
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
import uuid
from models import as_uuid
import mimetypes
import os

from models import (
    Document, DocumentVersion, DocumentShare, User, Organization, AuditLog
)

class DocumentService:
    """Service for document management with versioning and sharing"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # ========================================================================
    # Create & Upload Documents
    # ========================================================================
    
    def create_document(
        self,
        organization_id: str,
        created_by: str,
        name: str,
        document_type: str,  # contract, disclosure, proposal, agreement, etc.
        content: bytes,
        mime_type: Optional[str] = None,
        file_size: int = 0,
        client_id: Optional[str] = None,
        property_id: Optional[str] = None,
        deal_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        storage_location: Optional[str] = None,  # S3 path, local path, etc.
    ) -> Document:
        """
        Create a new document
        
        Args:
            organization_id: Organization UUID
            created_by: User UUID who created it
            name: Document name (e.g., "Purchase Agreement - 123 Main St")
            document_type: contract, disclosure, proposal, agreement, etc.
            content: Document content (bytes)
            mime_type: File MIME type (auto-detected if not provided)
            file_size: File size in bytes
            client_id: Optional associated client
            property_id: Optional associated property
            deal_id: Optional associated deal
            tags: Optional tags for search/organization
            metadata: Optional custom metadata
            storage_location: Where file is stored (S3, local, etc.)
        
        Returns:
            Created Document object
        """
        # Auto-detect MIME type
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(name)
            mime_type = mime_type or "application/octet-stream"
        
        document = Document(
            organization_id=as_uuid(organization_id),
            created_by=as_uuid(created_by),
            name=name,
            document_type=document_type,
            mime_type=mime_type,
            file_size=file_size or len(content),
            client_id=as_uuid(client_id) if client_id else None,
            property_id=as_uuid(property_id) if property_id else None,
            deal_id=as_uuid(deal_id) if deal_id else None,
            tags=tags or [],
            doc_metadata=metadata or {},
            storage_location=storage_location,
            version_number=1,
        )
        
        self.db.add(document)
        self.db.flush()
        
        # Create version 1
        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            created_by=as_uuid(created_by),
            content=content,
            mime_type=mime_type,
            file_size=file_size or len(content),
            storage_location=storage_location,
            change_notes="Initial version",
        )
        
        self.db.add(version)
        self.db.commit()
        self.db.refresh(document)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=created_by,
            action="document_created",
            entity_type="document",
            entity_id=str(document.id),
            new_values={
                "name": name,
                "document_type": document_type,
                "file_size": file_size,
            },
        )
        
        return document
    
    # ========================================================================
    # Read & Retrieve Documents
    # ========================================================================
    
    def get_document(
        self,
        document_id: str,
        organization_id: Optional[str] = None
    ) -> Optional[Document]:
        """Get document by ID"""
        query = self.db.query(Document).filter(
            Document.id == as_uuid(document_id),
            Document.deleted_at.is_(None),
        )
        
        if organization_id:
            query = query.filter(Document.organization_id == as_uuid(organization_id))
        
        return query.first()
    
    def list_documents(
        self,
        organization_id: str,
        skip: int = 0,
        limit: int = 50,
        document_type: Optional[str] = None,
        client_id: Optional[str] = None,
        property_id: Optional[str] = None,
        deal_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        search_term: Optional[str] = None,
        created_by: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[List[Document], int]:
        """
        List documents with optional filters
        
        Args:
            organization_id: Organization UUID
            skip: Number to skip
            limit: Number to return
            document_type: Filter by type
            client_id: Filter by client
            property_id: Filter by property
            deal_id: Filter by deal
            tags: Filter by tags (any match)
            search_term: Search in name & metadata
            created_by: Filter by creator
            date_from: Filter from date
            date_to: Filter to date
            sort_by: created_at or name
            sort_order: asc or desc
        
        Returns:
            Tuple of (documents list, total count)
        """
        query = self.db.query(Document).filter(
            Document.organization_id == as_uuid(organization_id),
            Document.deleted_at.is_(None),
        )
        
        # Apply filters
        if document_type:
            query = query.filter(Document.document_type == document_type)
        
        if client_id:
            query = query.filter(Document.client_id == as_uuid(client_id))
        
        if property_id:
            query = query.filter(Document.property_id == as_uuid(property_id))
        
        if deal_id:
            query = query.filter(Document.deal_id == as_uuid(deal_id))
        
        if created_by:
            query = query.filter(Document.created_by == as_uuid(created_by))
        
        if date_from:
            query = query.filter(Document.created_at >= date_from)
        
        if date_to:
            query = query.filter(Document.created_at <= date_to)
        
        # Search
        if search_term:
            query = query.filter(
                or_(
                    Document.name.ilike(f"%{search_term}%"),
                )
            )
        
        # Tag filtering
        if tags:
            for tag in tags:
                query = query.filter(Document.tags.contains([tag]))
        
        # Count total
        total = query.count()
        
        # Sort
        if sort_by == "name":
            query = query.order_by(
                Document.name.desc() if sort_order == "desc" else Document.name.asc()
            )
        else:  # created_at
            query = query.order_by(
                Document.created_at.desc() if sort_order == "desc" else Document.created_at.asc()
            )
        
        # Pagination
        documents = query.offset(skip).limit(limit).all()
        
        return documents, total
    
    def get_document_version(
        self,
        document_id: str,
        version_number: int,
    ) -> Optional[DocumentVersion]:
        """Get specific document version"""
        return self.db.query(DocumentVersion).filter(
            DocumentVersion.document_id == as_uuid(document_id),
            DocumentVersion.version_number == version_number,
        ).first()
    
    def list_document_versions(
        self,
        document_id: str,
        limit: int = 50,
    ) -> List[DocumentVersion]:
        """Get all versions of a document"""
        return self.db.query(DocumentVersion).filter(
            DocumentVersion.document_id == as_uuid(document_id)
        ).order_by(DocumentVersion.version_number.desc()).limit(limit).all()
    
    # ========================================================================
    # Update Documents (Versioning)
    # ========================================================================
    
    def update_document(
        self,
        document_id: str,
        organization_id: str,
        updated_by: str,
        content: bytes,
        change_notes: str = "Document updated",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Document:
        """
        Update document (creates new version)
        
        Args:
            document_id: Document UUID
            organization_id: Organization UUID
            updated_by: User UUID making update
            content: New content
            change_notes: Description of changes
            tags: Updated tags
            metadata: Updated metadata
        
        Returns:
            Updated Document object
        """
        document = self.get_document(document_id, organization_id)
        
        if not document:
            raise ValueError("Document not found")
        
        # Update document metadata
        document.updated_at = datetime.utcnow()
        document.updated_by = as_uuid(updated_by)
        
        if tags is not None:
            document.tags = tags
        
        if metadata is not None:
            document.doc_metadata = metadata
        
        # Increment version number
        new_version_number = document.version_number + 1
        document.version_number = new_version_number
        
        # Create new version
        version = DocumentVersion(
            document_id=as_uuid(document_id),
            version_number=new_version_number,
            created_by=as_uuid(updated_by),
            content=content,
            mime_type=document.mime_type,
            file_size=len(content),
            change_notes=change_notes,
        )
        
        self.db.add(version)
        self.db.commit()
        self.db.refresh(document)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=updated_by,
            action="document_updated",
            entity_type="document",
            entity_id=document_id,
            new_values={
                "version": new_version_number,
                "change_notes": change_notes,
            },
        )
        
        return document
    
    def rollback_version(
        self,
        document_id: str,
        organization_id: str,
        target_version: int,
        rolled_back_by: str,
    ) -> Document:
        """
        Rollback to a previous version
        
        Args:
            document_id: Document UUID
            organization_id: Organization UUID
            target_version: Version to rollback to
            rolled_back_by: User UUID rolling back
        
        Returns:
            Document at rolled-back version
        """
        document = self.get_document(document_id, organization_id)
        
        if not document:
            raise ValueError("Document not found")
        
        # Get target version
        target = self.get_document_version(document_id, target_version)
        
        if not target:
            raise ValueError(f"Version {target_version} not found")
        
        # Create new version from target
        new_version_number = document.version_number + 1
        
        version = DocumentVersion(
            document_id=as_uuid(document_id),
            version_number=new_version_number,
            created_by=as_uuid(rolled_back_by),
            content=target.content,
            mime_type=target.mime_type,
            file_size=target.file_size,
            change_notes=f"Rolled back from version {target_version}",
        )
        
        document.version_number = new_version_number
        document.updated_at = datetime.utcnow()
        document.updated_by = as_uuid(rolled_back_by)
        
        self.db.add(version)
        self.db.commit()
        self.db.refresh(document)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=rolled_back_by,
            action="document_rollback",
            entity_type="document",
            entity_id=document_id,
            new_values={
                "rolled_back_to_version": target_version,
                "new_version": new_version_number,
            },
        )
        
        return document
    
    # ========================================================================
    # Sharing & Permissions
    # ========================================================================
    
    def share_document(
        self,
        document_id: str,
        organization_id: str,
        shared_by: str,
        share_with_user_id: Optional[str] = None,
        share_with_email: Optional[str] = None,
        permission: str = "view",  # view, comment, edit
        expiry_date: Optional[datetime] = None,
    ) -> DocumentShare:
        """
        Share document with another user
        
        Args:
            document_id: Document UUID
            organization_id: Organization UUID
            shared_by: User UUID sharing
            share_with_user_id: User UUID to share with
            share_with_email: Email to share with (for external users)
            permission: view, comment, or edit
            expiry_date: Optional expiration date
        
        Returns:
            DocumentShare object
        """
        if not share_with_user_id and not share_with_email:
            raise ValueError("Either user_id or email must be provided")
        
        share = DocumentShare(
            document_id=as_uuid(document_id),
            organization_id=as_uuid(organization_id),
            shared_by=as_uuid(shared_by),
            share_with_user_id=as_uuid(share_with_user_id) if share_with_user_id else None,
            share_with_email=share_with_email,
            permission=permission,
            expiry_date=expiry_date,
        )
        
        self.db.add(share)
        self.db.commit()
        self.db.refresh(share)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=shared_by,
            action="document_shared",
            entity_type="document",
            entity_id=document_id,
            new_values={
                "shared_with": share_with_user_id or share_with_email,
                "permission": permission,
            },
        )
        
        return share
    
    def list_shared_with_me(
        self,
        user_id: str,
        organization_id: str,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[DocumentShare], int]:
        """Get documents shared with me"""
        query = self.db.query(DocumentShare).filter(
            DocumentShare.share_with_user_id == as_uuid(user_id),
            DocumentShare.organization_id == as_uuid(organization_id),
            or_(
                DocumentShare.expiry_date.is_(None),
                DocumentShare.expiry_date > datetime.utcnow(),
            ),
        )
        
        total = query.count()
        shares = query.offset(skip).limit(limit).all()
        
        return shares, total
    
    def revoke_share(
        self,
        share_id: str,
        organization_id: str,
        revoked_by: str,
    ) -> bool:
        """Revoke document share"""
        share = self.db.query(DocumentShare).filter(
            DocumentShare.id == as_uuid(share_id),
            DocumentShare.organization_id == as_uuid(organization_id),
        ).first()
        
        if not share:
            raise ValueError("Share not found")
        
        self.db.delete(share)
        self.db.commit()
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=revoked_by,
            action="document_share_revoked",
            entity_type="document",
            entity_id=str(share.document_id),
            new_values={"share_id": str(share_id)},
        )
        
        return True
    
    # ========================================================================
    # Compliance & Retention
    # ========================================================================
    
    def set_retention_policy(
        self,
        document_id: str,
        organization_id: str,
        retention_days: int,
        retention_reason: str = "regulatory",
    ) -> Document:
        """
        Set document retention policy
        
        Args:
            document_id: Document UUID
            organization_id: Organization UUID
            retention_days: Days to retain
            retention_reason: Reason for retention
        
        Returns:
            Updated Document
        """
        document = self.get_document(document_id, organization_id)
        
        if not document:
            raise ValueError("Document not found")
        
        document.retention_until = datetime.utcnow() + timedelta(days=retention_days)
        document.retention_reason = retention_reason
        self.db.commit()
        self.db.refresh(document)
        
        return document
    
    def get_expiring_documents(
        self,
        organization_id: str,
        days_until_expiry: int = 30,
    ) -> List[Document]:
        """Get documents expiring soon"""
        cutoff = datetime.utcnow() + timedelta(days=days_until_expiry)
        
        return self.db.query(Document).filter(
            Document.organization_id == as_uuid(organization_id),
            Document.retention_until.isnot(None),
            Document.retention_until <= cutoff,
            Document.deleted_at.is_(None),
        ).order_by(Document.retention_until.asc()).all()
    
    def mark_for_deletion(
        self,
        document_id: str,
        organization_id: str,
        marked_by: str,
        deletion_reason: str = "retention expired",
    ) -> Document:
        """Soft delete document"""
        document = self.get_document(document_id, organization_id)
        
        if not document:
            raise ValueError("Document not found")
        
        document.deleted_at = datetime.utcnow()
        document.deleted_by = as_uuid(marked_by)
        self.db.commit()
        self.db.refresh(document)
        
        # Log
        self._log_audit(
            organization_id=organization_id,
            user_id=marked_by,
            action="document_deleted",
            entity_type="document",
            entity_id=document_id,
            new_values={"deletion_reason": deletion_reason},
        )
        
        return document
    
    # ========================================================================
    # Document Analytics
    # ========================================================================
    
    def get_document_stats(
        self,
        organization_id: str,
        date_from: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get document statistics"""
        if not date_from:
            date_from = datetime.utcnow() - timedelta(days=30)
        
        query = self.db.query(Document).filter(
            Document.organization_id == as_uuid(organization_id),
            Document.created_at >= date_from,
            Document.deleted_at.is_(None),
        )
        
        documents = query.all()
        
        if not documents:
            return {
                "total_documents": 0,
                "by_type": {},
                "total_size_mb": 0,
                "average_size_kb": 0,
                "total_versions": 0,
            }
        
        # Calculate stats
        total_documents = len(documents)
        total_size = sum(d.file_size for d in documents)
        
        by_type = {}
        for doc in documents:
            by_type[doc.document_type] = by_type.get(doc.document_type, 0) + 1
        
        # Get version count
        total_versions = self.db.query(func.count(DocumentVersion.id)).filter(
            DocumentVersion.document_id.in_([d.id for d in documents])
        ).scalar() or 0
        
        return {
            "total_documents": total_documents,
            "by_type": by_type,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "average_size_kb": round(total_size / 1024 / total_documents, 2),
            "total_versions": total_versions,
        }
    
    # ========================================================================
    # Private Methods
    # ========================================================================
    
    def _log_audit(
        self,
        organization_id: str,
        user_id: Optional[str],
        action: str,
        entity_type: str = "document",
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
