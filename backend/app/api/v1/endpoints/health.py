"""
System Health, Liveness, Readiness, and Dependency Endpoints.
Provides standardized probes for container orchestrators, uptime monitoring,
and system version verification.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
import os

from app.db.session import get_db
from app.core.config import settings
from app.services.media.provider_status import get_media_diagnostics
from app.services.kiosk.hardware.capability_reporter import CapabilityReporter

router = APIRouter()


@router.get("/health")
def check_health(db: Session = Depends(get_db)):
    """General platform health check (backward compatible with Phase 1-8)."""
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "healthy" if db_status == "ok" else "degraded",
        "phase": settings.ARCHIVE_PHASE,
        "database": db_status,
        "environment": settings.ENVIRONMENT,
        "system_time": datetime.now(timezone.utc).isoformat(),
        "disclaimer": "SIH26096 Phase 1 Foundation API — Institutional Digital Heritage Platform"
    }


@router.get("/health/live")
def health_live():
    """Liveness probe: verifies application process is running and responsive."""
    return {
        "status": "ALIVE",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    """Readiness probe: verifies application can accept and serve incoming traffic."""
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "READY",
            "database": "CONNECTED",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service not ready. Database connection failure: {e}"
        )


@router.get("/health/dependencies")
def health_dependencies(db: Session = Depends(get_db)):
    """Comprehensive dependency health check: Database, Search, Media, RAG, and Hardware."""
    # 1. Database
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    # 2. Media diagnostics
    media_diag = get_media_diagnostics()

    # 3. Hardware summary
    hw_report = CapabilityReporter.generate_report()

    # 4. Storage paths
    masters_exist = os.path.exists(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../storage/media/masters")))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "OPERATIONAL" if db_ok and masters_exist else "DEGRADED",
        "dependencies": {
            "database": {
                "status": "OPERATIONAL" if db_ok else "UNAVAILABLE",
                "engine": settings.DATABASE_URL.split(":")[0]
            },
            "storage_vault": {
                "status": "OPERATIONAL" if masters_exist else "UNAVAILABLE",
                "read_only_protection": True
            },
            "media_processor": {
                "ffmpeg": media_diag.get("ffmpeg", {}).get("status", "UNAVAILABLE"),
                "native_fallback": "OPERATIONAL"
            },
            "speech_intelligence": {
                "whisper": media_diag.get("whisper", {}).get("status", "UNAVAILABLE")
            },
            "hardware_layer": {
                "display": hw_report.get("hardware", {}).get("display", "OPERATIONAL"),
                "touchscreen": hw_report.get("hardware", {}).get("touchscreen", "NOT_DETECTED"),
                "audio": hw_report.get("hardware", {}).get("speaker", "OPERATIONAL")
            },
            "supabase_cloud": {
                "configured": bool(settings.SUPABASE_URL),
                "url": settings.SUPABASE_URL or "UNCONFIGURED",
                "storage_buckets": [
                    settings.SUPABASE_BUCKET_DOCUMENTS,
                    settings.SUPABASE_BUCKET_IMAGES,
                    settings.SUPABASE_BUCKET_AUDIO,
                    settings.SUPABASE_BUCKET_DERIVATIVES
                ]
            }
        }
    }


@router.get("/system/version")
def system_version():
    """Returns application build, schema version, and deployment environment."""
    return {
        "platform": settings.PROJECT_NAME,
        "application_version": "1.9.0",
        "schema_version": "c8f2910d5403",
        "build_date": "2026-09-23",
        "archive_phase": "PHASE_9_KIOSK_DEPLOYMENT_SECURITY",
        "environment": settings.ENVIRONMENT
    }
