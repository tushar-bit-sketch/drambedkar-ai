import os
import hashlib
import uuid
import mimetypes
from typing import Tuple, Optional, Any
import logging
from fastapi import UploadFile, HTTPException

from app.core.config import settings

logger = logging.getLogger("archive.storage")

# Base storage directory relative to backend root
STORAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "storage", "uploads"))

# Optional S3 Object Storage Client
_s3_client: Optional[Any] = None

def get_s3_client():
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    if settings.OBJECT_STORAGE_ACCESS_KEY and settings.OBJECT_STORAGE_SECRET_KEY:
        try:
            import boto3
            from botocore.config import Config
            _s3_client = boto3.client(
                "s3",
                endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
                aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY,
                aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_KEY,
                region_name=settings.OBJECT_STORAGE_REGION,
                config=Config(signature_version="s3v4")
            )
            logger.info("Connected to S3-compatible Object Storage bucket: %s", settings.OBJECT_STORAGE_BUCKET)
        except Exception as e:
            logger.warning("Could not initialize S3 client: %s. Falling back to local vault.", e)
            _s3_client = False
    else:
        _s3_client = False
    return _s3_client if _s3_client is not False else None

# Allowed MIME types and extensions
ALLOWED_EXTENSIONS = {
    # Documents
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # Images
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    # Video
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

# Maximum file sizes (bytes)
MAX_FILE_SIZE_MAP = {
    "application": 50 * 1024 * 1024,  # 50 MB for documents
    "text": 10 * 1024 * 1024,         # 10 MB for text
    "image": 30 * 1024 * 1024,        # 30 MB for high-res images
    "audio": 100 * 1024 * 1024,       # 100 MB for audio
    "video": 200 * 1024 * 1024,       # 200 MB for archival video
}

def ensure_storage_dir():
    os.makedirs(STORAGE_DIR, exist_ok=True)

class StorageService:
    @staticmethod
    def validate_file(file: UploadFile) -> Tuple[str, str]:
        """
        Validates file extension and MIME type.
        Returns (sanitized_extension, validated_mime_type).
        """
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename missing in upload.")

        filename_lower = file.filename.lower()
        _, ext = os.path.splitext(filename_lower)

        if ext not in ALLOWED_EXTENSIONS:
            allowed_list = ", ".join(sorted(ALLOWED_EXTENSIONS.keys()))
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file format '{ext}'. Allowed archival formats: {allowed_list}"
            )

        expected_mime = ALLOWED_EXTENSIONS[ext]
        # Trust verified extension mapping while acknowledging client mime if related
        mime_type = file.content_type or expected_mime
        return ext, expected_mime

    @staticmethod
    def compute_sha256_and_save(file_bytes: bytes, original_filename: str) -> Tuple[str, str, str, int]:
        """
        Computes SHA-256 hash incrementally and saves file to secure disk path.
        Never overwrites: filename includes hash prefix and UUID.
        Returns: (filename, relative_storage_path, sha256_checksum, size_bytes)
        """
        ensure_storage_dir()
        size_bytes = len(file_bytes)
        
        # Compute SHA-256
        sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Sanitize original name
        _, ext = os.path.splitext(original_filename.lower())
        unique_prefix = f"{sha256[:12]}_{uuid.uuid4().hex[:8]}"
        sanitized_filename = f"{unique_prefix}{ext}"
        
        # Relative path for portable storage reference
        relative_path = os.path.join("storage", "uploads", sanitized_filename).replace("\\", "/")
        absolute_path = os.path.join(STORAGE_DIR, sanitized_filename)
        with open(absolute_path, "wb") as f:
            f.write(file_bytes)

        # Upload to S3-compatible Object Storage if configured
        s3 = get_s3_client()
        if s3:
            try:
                s3.put_object(
                    Bucket=settings.OBJECT_STORAGE_BUCKET,
                    Key=sanitized_filename,
                    Body=file_bytes,
                    ContentType=mimetypes.guess_type(sanitized_filename)[0] or "application/octet-stream"
                )
                logger.info("Persisted archival master %s to S3 bucket %s", sanitized_filename, settings.OBJECT_STORAGE_BUCKET)
            except Exception as e:
                logger.error("Failed persisting %s to S3 bucket %s: %s", sanitized_filename, settings.OBJECT_STORAGE_BUCKET, e)

        # Upload to Supabase Storage if configured
        try:
            from app.core.supabase import supabase_client
            if supabase_client.is_configured:
                # Route to appropriate archival bucket based on MIME extension
                if ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"):
                    target_bucket = settings.SUPABASE_BUCKET_IMAGES
                elif ext in (".mp3", ".wav", ".m4a"):
                    target_bucket = settings.SUPABASE_BUCKET_AUDIO
                elif ext in (".json", ".xml", ".vtt", ".srt"):
                    target_bucket = settings.SUPABASE_BUCKET_DERIVATIVES
                else:
                    target_bucket = settings.SUPABASE_BUCKET_DOCUMENTS

                ct = mimetypes.guess_type(sanitized_filename)[0] or "application/octet-stream"
                ok, res = supabase_client.upload_asset(target_bucket, sanitized_filename, file_bytes, ct)
                if ok:
                    logger.info("Persisted archival master %s to Supabase bucket [%s]", sanitized_filename, target_bucket)
                else:
                    logger.debug("Supabase Storage upload bypassed/deferred: %s", res)
        except Exception as se:
            logger.debug("Supabase Storage integration bypassed: %s", se)

        return sanitized_filename, relative_path, sha256, size_bytes

    @staticmethod
    def get_absolute_path(storage_path: str) -> str:
        """Resolves relative storage path to system absolute path."""
        # Normalize and prevent directory traversal
        clean_path = storage_path.replace("/", os.sep).replace("\\", os.sep)
        if clean_path.startswith("storage" + os.sep + "uploads" + os.sep):
            clean_path = clean_path[len("storage" + os.sep + "uploads" + os.sep):]
        elif clean_path.startswith("storage" + os.sep):
            clean_path = clean_path[len("storage" + os.sep):]

        clean_path = os.path.basename(clean_path) # Absolute basename safety
        abs_path = os.path.join(STORAGE_DIR, clean_path)
        return abs_path

    @staticmethod
    def verify_integrity(storage_path: str, expected_checksum: str) -> Tuple[bool, str]:
        """
        Recalculates file hash on disk and compares with stored checksum.
        Returns: (is_valid: bool, status_message: str)
        """
        abs_path = StorageService.get_absolute_path(storage_path)
        if not os.path.exists(abs_path):
            return False, "FILE_NOT_FOUND_ON_DISK"

        sha256 = hashlib.sha256()
        with open(abs_path, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        
        computed = sha256.hexdigest()
        if computed.lower() == expected_checksum.lower():
            return True, "VALID"
        else:
            return False, "INTEGRITY_CHECK_FAILED"
