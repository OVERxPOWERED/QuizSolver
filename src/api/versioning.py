from enum import Enum
from typing import Optional, List, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import FastAPI, Request, Response, APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class APIVersion(str, Enum):
    """Supported API versions with semantic versioning."""
    V1 = "v1"
    V2 = "v2"

    @property
    def major(self) -> int:
        return int(self.value[1:])

    @property
    def media_type(self) -> str:
        return f"application/vnd.quizauto.{self.value}+json"

    @property
    def url_prefix(self) -> str:
        return f"/api/{self.value}"

    def is_deprecated(self) -> bool:
        return self == APIVersion.V1

    def deprecation_date(self) -> Optional[str]:
        if self == APIVersion.V1:
            return "2025-12-31"
        return None

    def sunset_date(self) -> Optional[str]:
        if self == APIVersion.V1:
            return "2026-06-30"
        return None

    def release_date(self) -> str:
        if self == APIVersion.V1:
            return "2024-01-15"
        return "2025-01-15"


@dataclass
class VersionConfig:
    """Metadata for a specific API version."""
    version: APIVersion
    release_date: str
    sunset_date: Optional[str]
    is_deprecated: bool


class VersioningSettings(BaseSettings):
    """Configuration for API versioning."""
    default_version: APIVersion = APIVersion.V2
    supported_versions: List[APIVersion] = field(default_factory=lambda: [APIVersion.V1, APIVersion.V2])
    deprecated_versions: List[APIVersion] = field(default_factory=lambda: [APIVersion.V1])
    version_header_name: str = "API-Version"
    deprecation_header_name: str = "Deprecation"
    sunset_header_name: str = "Sunset"
    accept_header_prefix: str = "application/vnd.quizauto."
    accept_header_suffix: str = "+json"

    class Config:
        env_prefix = "API_VERSION_"
        case_sensitive = False


@dataclass
class VersionInfo:
    """Information about a negotiated API version."""
    version: APIVersion
    source: str  # "header", "url", "default"
    is_deprecated: bool
    deprecation_date: Optional[str]
    sunset_date: Optional[str]


class VersionNegotiator:
    """
    Negotiates API version from Accept header, URL path, or defaults.
    
    Priority order:
    1. Accept header (application/vnd.quizauto.v1+json)
    2. URL path prefix (/api/v1/...)
    3. Default version from config
    """

    def __init__(self, config: Optional[VersioningSettings] = None):
        self.config = config or VersioningSettings()
        self._version_patterns = {
            version: version.media_type for version in self.config.supported_versions
        }

    def parse_accept_header(self, accept: str) -> Optional[APIVersion]:
        """Parse version from Accept header."""
        if not accept:
            return None
        
        # Handle multiple accept values, take first matching
        for part in accept.split(","):
            part = part.strip()
            # Remove quality parameters
            media_type = part.split(";")[0].strip()
            
            for version, expected_type in self._version_patterns.items():
                if media_type == expected_type or media_type == f"{expected_type};q=1.0":
                    return version
                
                # Also support wildcard matching for major version
                if media_type.startswith(self.config.accept_header_prefix):
                    version_str = media_type[len(self.config.accept_header_prefix):]
                    version_str = version_str.removesuffix(self.config.accept_header_suffix)
                    try:
                        return APIVersion(version_str)
                    except ValueError:
                        continue
        return None

    def parse_url_path(self, path: str) -> Optional[APIVersion]:
        """Parse version from URL path prefix."""
        if not path:
            return None
        
        # Normalize path
        path = path.rstrip("/")
        
        for version in self.config.supported_versions:
            if path.startswith(version.url_prefix):
                # Ensure it's a prefix match (not partial like /api/v10)
                remainder = path[len(version.url_prefix):]
                if remainder == "" or remainder.startswith("/"):
                    return version
        return None

    def negotiate_version(
        self, 
        accept_header: Optional[str], 
        url_path: str,
        x_api_version_header: Optional[str] = None
    ) -> VersionInfo:
        """
        Negotiate version using priority order.
        
        Args:
            accept_header: Value of Accept header
            url_path: Request URL path
            x_api_version_header: Value of X-API-Version header (fallback)
            
        Returns:
            VersionInfo with negotiated version and metadata
        """
        # 1. Try Accept header
        version = self.parse_accept_header(accept_header) if accept_header else None
        source = "header"
        
        # 2. Try X-API-Version header (explicit version override)
        if version is None and x_api_version_header:
            try:
                version = APIVersion(x_api_version_header.strip())
                source = "x-api-version-header"
            except ValueError:
                pass
        
        # 3. Try URL path
        if version is None:
            version = self.parse_url_path(url_path)
            source = "url"
        
        # 4. Fallback to default
        if version is None:
            version = self.config.default_version
            source = "default"
        
        # Validate version is supported
        if version not in self.config.supported_versions:
            version = self.config.default_version
            source = "default (unsupported requested)"
        
        return VersionInfo(
            version=version,
            source=source,
            is_deprecated=version.is_deprecated(),
            deprecation_date=version.deprecation_date(),
            sunset_date=version.sunset_date()
        )


# Response transformer registry
ResponseTransformer = Callable[[Dict[str, Any], APIVersion], Awaitable[Dict[str, Any]]]
_transformers: Dict[APIVersion, ResponseTransformer] = {}


def register_response_transformer(version: APIVersion, transformer: ResponseTransformer) -> None:
    """Register a response transformer for a specific API version."""
    _transformers[version] = transformer


async def transform_response(response_data: Dict[str, Any], target_version: APIVersion) -> Dict[str, Any]:
    """Apply version-specific response transformation."""
    if target_version in _transformers:
        return await _transformers[target_version](response_data, target_version)
    return response_data


# Default transformers for backward compatibility
async def _v1_transformer(data: Dict[str, Any], version: APIVersion) -> Dict[str, Any]:
    """Transform v2 response format to v1 format."""
    # Example: v2 uses 'quiz_id', v1 used 'id'
    if isinstance(data, dict):
        transformed = data.copy()
        if "quiz_id" in transformed:
            transformed["id"] = transformed.pop("quiz_id")
        if "created_at" in transformed and "createdAt" not in transformed:
            transformed["createdAt"] = transformed.pop("created_at")
        return transformed
    return data


async def _v2_transformer(data: Dict[str, Any], version: APIVersion) -> Dict[str, Any]:
    """v2 is current format, no transformation needed."""
    return data


# Register default transformers
register_response_transformer(APIVersion.V1, _v1_transformer)
register_response_transformer(APIVersion.V2, _v2_transformer)


class VersioningMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware for API version negotiation and response header injection.
    
    Handles:
    - Version negotiation via Accept header, X-API-Version header, or URL path
    - Injection of API-Version, Deprecation, and Sunset response headers
    - Backward-compatible response transformation
    """

    def __init__(
        self, 
        app: ASGIApp, 
        config: Optional[VersioningSettings] = None,
        negotiator: Optional[VersionNegotiator] = None
    ):
        super().__init__(app)
        self.config = config or VersioningSettings()
        self.negotiator = negotiator or VersionNegotiator(self.config)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Negotiate version
        accept_header = request.headers.get("accept")
        x_api_version = request.headers.get("x-api-version")
        version_info = self.negotiator.negotiate_version(
            accept_header=accept_header,
            url_path=request.url.path,
            x_api_version_header=x_api_version
        )
        
        # Store version info in request state for route access
        request.state.api_version = version_info
        
        # Process request
        response = await call_next(request)
        
        # Inject version headers
        self._inject_version_headers(response, version_info)
        
        # Transform response body for backward compatibility (only for JSON responses)
        if version_info.version != self.config.default_version:
            response = await self._transform_response_body(response, version_info.version)
        
        return response

    def _inject_version_headers(self, response: Response, version_info: VersionInfo) -> None:
        """Inject version-related headers into response."""
        headers = MutableHeaders(scope=response)
        headers[self.config.version_header_name] = version_info.version.value
        
        if version_info.is_deprecated