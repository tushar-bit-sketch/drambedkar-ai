"""
=============================================================================
SIH26096: Ambedkar Digital Heritage Archive
SUPABASE INTEGRATION LAYER (MANAGED CLOUD BACKEND)
=============================================================================
Provides unified, resilient access to:
1. Supabase Managed Storage (Buckets: archive-documents, archive-images, archive-audio, archive-derivatives)
2. Supabase Auth & JWT Verification (With fallback to local HMAC tokens)
3. Supabase REST API & Connection Health Checks
=============================================================================
"""

import os
import logging
import mimetypes
from typing import Optional, Dict, Any, Tuple
import httpx
from jose import jwt

from app.core.config import settings

logger = logging.getLogger("archive.supabase")

class SupabaseClient:
    """
    Direct, lightweight HTTP client for Supabase cloud services.
    Uses httpx and standard REST endpoints so it does not fail if optional SDKs are missing.
    """

    def __init__(self):
        self.url = (settings.SUPABASE_URL or "").strip().rstrip("/")
        self.anon_key = (settings.SUPABASE_ANON_KEY or "").strip()
        self.service_role_key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
        self.jwt_secret = (settings.SUPABASE_JWT_SECRET or "").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.url and (self.anon_key or self.service_role_key))

    @property
    def has_admin_access(self) -> bool:
        return bool(self.url and self.service_role_key)

    def _get_headers(self, use_service_role: bool = False) -> Dict[str, str]:
        key = self.service_role_key if (use_service_role and self.service_role_key) else self.anon_key
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

    # -------------------------------------------------------------------------
    # Storage Operations
    # -------------------------------------------------------------------------

    def upload_asset(
        self,
        bucket: str,
        path: str,
        data: bytes,
        content_type: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Uploads an archival asset into the specified Supabase Storage bucket.
        Returns: (success: bool, url_or_error: Optional[str])
        """
        if not self.is_configured:
            return False, "SUPABASE_UNCONFIGURED"

        clean_path = path.lstrip("/")
        if not content_type:
            content_type = mimetypes.guess_type(clean_path)[0] or "application/octet-stream"

        endpoint = f"{self.url}/storage/v1/object/{bucket}/{clean_path}"
        headers = self._get_headers(use_service_role=True)
        headers["Content-Type"] = content_type
        # Overwrite existing object safely if upsert requested
        headers["x-upsert"] = "true"

        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(endpoint, headers=headers, content=data)
                if res.status_code in (200, 201):
                    public_url = f"{self.url}/storage/v1/object/public/{bucket}/{clean_path}"
                    logger.info("Uploaded asset to Supabase Storage [%s]: %s", bucket, clean_path)
                    return True, public_url
                else:
                    error_msg = f"HTTP {res.status_code}: {res.text}"
                    logger.error("Supabase Storage upload failed: %s", error_msg)
                    return False, error_msg
        except Exception as e:
            logger.error("Exception during Supabase Storage upload: %s", e)
            return False, str(e)

    def download_asset(self, bucket: str, path: str) -> Optional[bytes]:
        """Downloads an asset from Supabase Storage."""
        if not self.is_configured:
            return None

        clean_path = path.lstrip("/")
        endpoint = f"{self.url}/storage/v1/object/{bucket}/{clean_path}"
        headers = self._get_headers(use_service_role=True)

        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.get(endpoint, headers=headers)
                if res.status_code == 200:
                    return res.content
                return None
        except Exception as e:
            logger.error("Failed downloading asset from Supabase: %s", e)
            return None

    def get_public_url(self, bucket: str, path: str) -> str:
        """Returns public URL for an asset in Supabase Storage."""
        clean_path = path.lstrip("/")
        if not self.url:
            return f"/storage/{bucket}/{clean_path}"
        return f"{self.url}/storage/v1/object/public/{bucket}/{clean_path}"

    def ensure_buckets(self) -> Dict[str, bool]:
        """
        Idempotently verifies and provisions required archival buckets:
        archive-documents, archive-images, archive-audio, archive-derivatives.
        """
        if not self.has_admin_access:
            return {"error": "Admin service role key required"}

        required_buckets = [
            settings.SUPABASE_BUCKET_DOCUMENTS,
            settings.SUPABASE_BUCKET_IMAGES,
            settings.SUPABASE_BUCKET_AUDIO,
            settings.SUPABASE_BUCKET_DERIVATIVES,
        ]

        results = {}
        headers = self._get_headers(use_service_role=True)

        try:
            with httpx.Client(timeout=25.0) as client:
                # 1. Fetch existing buckets in one shot
                res = client.get(f"{self.url}/storage/v1/bucket", headers=headers)
                existing = set()
                if res.status_code == 200:
                    try:
                        existing = {b["id"] for b in res.json() if "id" in b}
                    except Exception:
                        pass

                # 2. Provision any missing buckets
                for b in required_buckets:
                    if b in existing:
                        results[b] = True
                    else:
                        create_res = client.post(
                            f"{self.url}/storage/v1/bucket",
                            headers=headers,
                            json={"id": b, "name": b, "public": True}
                        )
                        results[b] = create_res.status_code in (200, 201)
        except Exception as e:
            logger.error("Error ensuring Supabase buckets: %s", e)
            results["error"] = str(e)

        return results

    # -------------------------------------------------------------------------
    # Authentication & JWT Validation
    # -------------------------------------------------------------------------

    def verify_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validates Supabase-issued JWTs.
        Extracts user claims, email, and mapped institutional role.
        """
        secret = self.jwt_secret or self.service_role_key or settings.SECRET_KEY
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                options={"verify_aud": False}
            )
            # Map Supabase role or user_metadata to institutional RBAC
            user_meta = payload.get("user_metadata", {})
            app_meta = payload.get("app_metadata", {})
            
            raw_role = (
                user_meta.get("role") or 
                app_meta.get("role") or 
                payload.get("role") or 
                "VISITOR"
            ).upper()

            # Normalize to canonical 5 roles
            if raw_role in ("SUPER_ADMIN", "ADMIN", "DIRECTOR"):
                canonical_role = "SUPER_ADMIN"
            elif raw_role in ("ARCHIVIST", "CURATOR"):
                canonical_role = "ARCHIVIST"
            elif raw_role in ("REVIEWER", "PEER_REVIEWER"):
                canonical_role = "REVIEWER"
            elif raw_role in ("RESEARCHER", "SCHOLAR"):
                canonical_role = "RESEARCHER"
            else:
                canonical_role = "VISITOR"

            payload["institutional_role"] = canonical_role
            return payload
        except Exception as e:
            logger.debug("Supabase JWT validation failed: %s", e)
            return None

    # -------------------------------------------------------------------------
    # Health Diagnostics
    # -------------------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """Performs non-blocking diagnostic probes against Supabase services."""
        diag = {
            "configured": self.is_configured,
            "url": self.url or "NONE",
            "has_service_role": self.has_admin_access,
            "database_connected": False,
            "storage_status": "UNCONFIGURED",
        }

        if not self.is_configured:
            return diag

        headers = self._get_headers(use_service_role=False)
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.url}/storage/v1/bucket", headers=headers)
                diag["storage_status"] = "REACHABLE" if res.status_code == 200 else f"HTTP_{res.status_code}"
        except Exception as e:
            diag["storage_status"] = f"ERROR: {str(e)[:100]}"

        return diag

# Global Singleton
supabase_client = SupabaseClient()
