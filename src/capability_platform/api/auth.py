from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from capability_platform.access.credentials import verify_password
from capability_platform.access.models import ClientCredential
from capability_platform.models import ServiceType
from capability_platform.runtime import credential_store

_security = HTTPBasic()


def authenticate_client(
    credentials: HTTPBasicCredentials = Depends(_security),  # noqa: B008 - FastAPI's own idiom
) -> ClientCredential:
    record = credential_store().get(credentials.username)
    if (
        record is None
        or not record.active
        or not verify_password(credentials.password, record.password_hash, record.password_salt)
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid client credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return record


def require_service_type(service_type: ServiceType, credential: ClientCredential) -> None:
    if service_type not in credential.authorized_service_types:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Client '{credential.client_id}' is not authorized for service_type={service_type}",
        )
