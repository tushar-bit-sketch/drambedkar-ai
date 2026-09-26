from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Optional
from pydantic import BaseModel

from app.db.session import get_db
from app.db.models import User, Role
from app.core.security import verify_password, create_access_token, decode_access_token
from app.core.config import settings
from app.schemas.user import Token, UserOut

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token", auto_error=False)

class LoginRequest(BaseModel):
    email: str
    password: str

def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    if not token:
        return None
    
    # 1. Try local institutional JWT
    payload = decode_access_token(token)
    if payload and "sub" in payload:
        try:
            user_id = int(payload.get("sub"))
            return db.query(User).filter(User.id == user_id).first()
        except (ValueError, TypeError):
            pass

    # 2. Try Supabase Auth JWT
    try:
        from app.core.supabase import supabase_client
        sb_payload = supabase_client.verify_jwt(token)
        if sb_payload:
            email = sb_payload.get("email")
            if email:
                user = db.query(User).filter(User.email == email.strip()).first()
                if user:
                    return user
                # Provision or bind authenticated Supabase user with mapped role
                role_name = sb_payload.get("institutional_role", "VISITOR")
                role = db.query(Role).filter(Role.name == role_name).first()
                if not role:
                    role = db.query(Role).filter(Role.name == "VISITOR").first()
                
                new_user = User(
                    email=email.strip(),
                    full_name=sb_payload.get("user_metadata", {}).get("full_name") or email.split("@")[0].title(),
                    hashed_password="SUPABASE_MANAGED_AUTH",
                    is_active=True,
                    role_id=role.id if role else 1
                )
                db.add(new_user)
                db.commit()
                db.refresh(new_user)
                return new_user
    except Exception:
        pass

    return None

def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    user = get_current_user_optional(token=token, db=db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user

def require_role(allowed_roles: list[str]):
    def role_checker(
        token: Optional[str] = Depends(oauth2_scheme),
        db: Session = Depends(get_db)
    ) -> User:
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials required for administrative access",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = get_current_user_optional(token=token, db=db)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive or removed")

        user_role = user.role.name if user.role else "VISITOR"
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Requires one of {allowed_roles}. Current role: {user_role}"
            )
        return user
    return role_checker

@router.post("/token", response_model=Token)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == form_data.username.strip()).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect archival staff email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account is disabled")

    role_name = user.role.name if user.role else "VISITOR"
    access_token = create_access_token(
        subject=user.id,
        role=role_name,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        role=role_name,
        user_name=user.full_name
    )

@router.post("/login", response_model=Token)
def login_json(
    body: LoginRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == body.email.strip()).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect archival staff email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role_name = user.role.name if user.role else "VISITOR"
    access_token = create_access_token(
        subject=user.id,
        role=role_name,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        role=role_name,
        user_name=user.full_name
    )

@router.get("/me", response_model=UserOut)
def read_current_user(
    current_user: User = Depends(require_role(["SUPER_ADMIN", "ARCHIVIST", "RESEARCHER", "REVIEWER", "VISITOR"]))
):
    return current_user
