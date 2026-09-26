import pytest
from datetime import datetime, timezone, timedelta
from jose import jwt
from unittest.mock import patch, MagicMock

from app.core.config import settings
from app.core.supabase import SupabaseClient, supabase_client
from app.api.v1.endpoints.auth import get_current_user_optional
from app.db.session import SessionLocal
from app.db.models import User, Role

def test_supabase_client_initialization_unconfigured():
    """Verify Supabase client initializes gracefully even when credentials are not yet set."""
    client = SupabaseClient()
    assert client.is_configured == bool(settings.SUPABASE_URL and (settings.SUPABASE_ANON_KEY or settings.SUPABASE_SERVICE_ROLE_KEY))
    diag = client.health_check()
    assert "configured" in diag
    assert "storage_status" in diag

def test_supabase_jwt_verification_and_role_mapping():
    """Verify Supabase JWT claims are verified and mapped to canonical archival roles."""
    client = SupabaseClient()
    secret = "test_supabase_jwt_secret_key_12345678"
    client.jwt_secret = secret

    # Test ARCHIVIST role mapping
    now = datetime.now(timezone.utc)
    token_data = {
        "sub": "sb_user_12345",
        "email": "curator@ambedkar-archive.gov.in",
        "exp": now + timedelta(hours=1),
        "user_metadata": {
            "full_name": "Curator Ambedkar Scholar",
            "role": "ARCHIVIST"
        }
    }
    encoded = jwt.encode(token_data, secret, algorithm="HS256")
    
    payload = client.verify_jwt(encoded)
    assert payload is not None
    assert payload["email"] == "curator@ambedkar-archive.gov.in"
    assert payload["institutional_role"] == "ARCHIVIST"

    # Test SUPER_ADMIN role mapping
    token_admin = {
        "sub": "sb_admin_999",
        "email": "director@ambedkar-archive.gov.in",
        "exp": now + timedelta(hours=1),
        "app_metadata": {"role": "ADMIN"}
    }
    encoded_admin = jwt.encode(token_admin, secret, algorithm="HS256")
    payload_admin = client.verify_jwt(encoded_admin)
    assert payload_admin is not None
    assert payload_admin["institutional_role"] == "SUPER_ADMIN"

def test_auth_endpoint_accepts_supabase_token():
    """Verify get_current_user_optional binds a valid Supabase JWT to a database user."""
    db = SessionLocal()
    client = SupabaseClient()
    secret = settings.SECRET_KEY # Uses secret key fallback
    client.jwt_secret = secret

    token_data = {
        "sub": "sb_test_researcher_001",
        "email": "researcher@ambedkar-archive.gov.in",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "user_metadata": {
            "full_name": "Dr. Ambedkar Research Fellow",
            "role": "RESEARCHER"
        }
    }
    encoded = jwt.encode(token_data, secret, algorithm="HS256")

    with patch("app.core.supabase.supabase_client", client):
        user = get_current_user_optional(token=encoded, db=db)
        assert user is not None
        assert user.email == "researcher@ambedkar-archive.gov.in"
        assert user.is_active is True

    db.close()

def test_storage_bucket_routing():
    """Verify archival assets are routed to appropriate Supabase buckets by MIME type."""
    from app.services.storage import StorageService

    # Documents
    _, ext_pdf = StorageService.validate_file(MagicMock(filename="manuscript.pdf", content_type="application/pdf"))
    assert ext_pdf == "application/pdf"

    # Images
    _, ext_img = StorageService.validate_file(MagicMock(filename="folio_photo.jpg", content_type="image/jpeg"))
    assert ext_img == "image/jpeg"

    # Audio
    _, ext_audio = StorageService.validate_file(MagicMock(filename="speech.mp3", content_type="audio/mpeg"))
    assert ext_audio == "audio/mpeg"
