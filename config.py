"""
Configuration management for the Real Estate CRM
Environment-based configuration with sensible defaults
"""

from pydantic_settings import BaseSettings
from typing import List
from functools import lru_cache
import os

class Settings(BaseSettings):
    """Application settings"""
    
    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = ENVIRONMENT == "development"
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/real_estate_crm"
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # API Configuration
    API_V1_STR: str = "/api/v1"
    API_TITLE: str = "Real Estate CRM"
    API_DESCRIPTION: str = "Comprehensive CRM for property sales and rentals"
    API_VERSION: str = "1.0.0"
    
    # Security
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "your-secret-key-change-in-production"
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # JWT
    JWT_PRIVATE_KEY: str = os.getenv("JWT_PRIVATE_KEY", "")
    JWT_PUBLIC_KEY: str = os.getenv("JWT_PUBLIC_KEY", "")
    
    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://localhost:3000",
        "https://localhost:5173",
    ]
    ALLOWED_HOSTS: List[str] = [
        "localhost",
        "127.0.0.1",
        "*.example.com",
    ]
    
    # File Storage (S3 or MinIO)
    FILE_STORAGE_TYPE: str = os.getenv("FILE_STORAGE_TYPE", "s3")  # s3 or minio
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "real-estate-crm")
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY", "")
    S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY", "")
    S3_ENDPOINT_URL: str = os.getenv("S3_ENDPOINT_URL", "")
    
    # MinIO (alternative to S3)
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "")
    
    # Redis (caching & sessions)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 5
    REDIS_SOCKET_TIMEOUT: int = 5
    
    # Email Configuration
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "noreply@realestate-crm.com")
    
    # Twilio (for call logging)
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")
    
    # AI/ML Services
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    PINECONE_API_KEY: str = os.getenv("PINECONE_API_KEY", "")
    PINECONE_ENVIRONMENT: str = os.getenv("PINECONE_ENVIRONMENT", "")
    
    # Google Services
    GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = "json"
    
    # Features
    ENABLE_CALL_LOGGING: bool = True
    ENABLE_AI_SUMMARIES: bool = True
    ENABLE_PROPERTY_MATCHING: bool = True
    ENABLE_REPORTING: bool = True
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD_SECONDS: int = 60
    
    # Pagination
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 1000
    
    # Search
    ELASTICSEARCH_URL: str = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    ENABLE_ELASTICSEARCH: bool = False
    
    # Multi-tenancy
    ENABLE_MULTI_TENANCY: bool = True
    
    # Supported Languages
    SUPPORTED_LANGUAGES: List[str] = ["en", "ru", "hy", "fa"]
    DEFAULT_LANGUAGE: str = "en"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()

# Create settings instance
settings = get_settings()

# ============================================================================
# Database Configuration
# ============================================================================
DATABASE_CONFIG = {
    "url": settings.DATABASE_URL,
    "pool_size": settings.DATABASE_POOL_SIZE,
    "max_overflow": settings.DATABASE_MAX_OVERFLOW,
    "echo": settings.DEBUG,
}

# ============================================================================
# API Configuration
# ============================================================================
API_CONFIG = {
    "title": settings.API_TITLE,
    "description": settings.API_DESCRIPTION,
    "version": settings.API_VERSION,
    "docs_url": "/docs" if settings.DEBUG else None,
    "redoc_url": "/redoc" if settings.DEBUG else None,
}

# ============================================================================
# Storage Configuration Factory
# ============================================================================
def get_storage_config():
    """Get storage configuration based on type"""
    if settings.FILE_STORAGE_TYPE == "s3":
        return {
            "type": "s3",
            "bucket": settings.S3_BUCKET_NAME,
            "region": settings.S3_REGION,
            "access_key": settings.S3_ACCESS_KEY,
            "secret_key": settings.S3_SECRET_KEY,
            "endpoint_url": settings.S3_ENDPOINT_URL,
        }
    elif settings.FILE_STORAGE_TYPE == "minio":
        return {
            "type": "minio",
            "endpoint": settings.MINIO_ENDPOINT,
            "access_key": settings.MINIO_ACCESS_KEY,
            "secret_key": settings.MINIO_SECRET_KEY,
        }
    else:
        raise ValueError(f"Unknown storage type: {settings.FILE_STORAGE_TYPE}")

# ============================================================================
# Example .env file
# ============================================================================
"""
# .env file example

ENVIRONMENT=development
DEBUG=True

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/real_estate_crm

# Security
SECRET_KEY=your-super-secret-key-change-in-production
ALGORITHM=HS256

# JWT
JWT_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----...
JWT_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----...

# File Storage
FILE_STORAGE_TYPE=s3
S3_BUCKET_NAME=real-estate-crm
S3_REGION=us-east-1
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key

# Redis
REDIS_URL=redis://localhost:6379/0

# Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password

# Twilio
TWILIO_ACCOUNT_SID=your-account-sid
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+1234567890

# AI Services
OPENAI_API_KEY=sk-...
PINECONE_API_KEY=your-pinecone-key
PINECONE_ENVIRONMENT=production

# Google
GOOGLE_MAPS_API_KEY=your-google-maps-key

# Logging
LOG_LEVEL=INFO
"""
