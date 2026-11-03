from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response, APIRouter
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Headers
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


class VersionConfig(BaseSettings):
    """Configuration for API versioning."""
    default_version: APIVersion = APIVersion.V2
    supported_versions: List[APIVersion] = [APIVersion.V1, APIVersion.V2]
    deprecated_versions: List[APIVersion] = [APIVersion.V1]
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

    def __init__(self, config: Optional[VersionConfig] = None):
        self.config = config or VersionConfig()
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
                if not remainder or remainder.startswith("/"):
                    return version
        return None

    def negotiate(self, request: Request) -> VersionInfo:
        """
        Negotiate version from request.
        
        Returns VersionInfo with negotiated version and metadata.
        """
        # 1. Try Accept header
        accept = request.headers.get("accept", "")
        version = self.parse_accept_header(accept)
        if version:
            return self._build_version_info(version, "header")

        # 2. Try URL path
        version = self.parse_url_path(request.url.path)
        if version:
            return self._build_version_info(version, "url")

        # 3. Default
        return self._build_version_info(self.config.default_version, "default")

    def _build_version_info(self, version: APIVersion, source: str) -> VersionInfo:
        return VersionInfo(
            version=version,
            source=source,
            is_deprecated=version in self.config.deprecated_versions,
            deprecation_date=version.deprecation_date(),
            sunset_date=version.sunset_date(),
        )

    def to_headers(self, version_info: VersionInfo) -> Dict[str, str]:
        """Convert version info to response headers."""
        headers = {
            self.config.version_header_name: version_info.version.value,
        }
        
        if version_info.is_deprecated:
            headers[self.config.deprecation_header_name] = "true"
            if version_info.deprecation_date:
                headers[self.config.deprecation_header_name] += f"; deprecation-date={version_info.deprecation_date}"
            if version_info.sunset_date:
                headers[self.config.sunset_header_name] = version_info.sunset_date
        
        return headers


class VersioningMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that adds version headers to all responses.
    
    Adds:
    - API-Version: The negotiated version
    - Deprecation: true (if deprecated) with optional date
    - Sunset: Sunset date (if deprecated)
    """

    def __init__(self, app: FastAPI, negotiator: Optional[VersionNegotiator] = None):
        super().__init__(app)
        self.negotiator = negotiator or VersionNegotiator()

    async def dispatch(self, request: Request, call_next):
        # Negotiate version for this request
        version_info = self.negotiator.negotiate(request)
        
        # Store version info in request state for route handlers
        request.state.api_version = version_info
        
        # Process request
        response = await call_next(request)
        
        # Add version headers to response
        headers = self.negotiator.to_headers(version_info)
        for key, value in headers.items():
            response.headers[key] = value
        
        # Add Vary header for proper caching
        response.headers["Vary"] = "Accept"
        
        return response


def include_versioned_routes(
    app: FastAPI,
    routers: Dict[APIVersion, APIRouter],
    prefix: str = "",
    tags: Optional[List[str]] = None,
    **kwargs: Any
) -> None:
    """
    Include versioned routers with proper prefixes.
    
    Args:
        app: FastAPI application
        routers: Dict mapping APIVersion to APIRouter
        prefix: Additional prefix to prepend (e.g., "/api")
        tags: OpenAPI tags for all routes
        **kwargs: Additional arguments passed to include_router
    """
    config = VersionConfig()
    
    for version, router in routers.items():
        if version not in config.supported_versions:
            continue
            
        version_prefix = f"{prefix}{version.url_prefix}"
        
        # Add deprecation info to router tags if deprecated
        router_tags = list(tags) if tags else []
        if version in config.deprecated_versions:
            router_tags.append("deprecated")
        
        app.include_router(
            router,
            prefix=version_prefix,
            tags=router_tags,
            **kwargs
        )


# Default instances for easy importing
version_config = VersionConfig()
version_negotiator = VersionNegotiator(version_config)


def create_versioning_middleware(app: FastAPI) -> VersioningMiddleware:
    """Factory function to create versioning middleware with default negotiator."""
    return VersioningMiddleware(app, version_negotiator)


# Convenience function for getting version from request state
def get_api_version(request: Request) -> VersionInfo:
    """Get negotiated API version from request state."""
    return getattr(request.state, "api_version", version_negotiator._build_version_info(
        version_config.default_version, "default"
    ))


# Dependency for FastAPI route handlers
async def api_version_dependency(request: Request) -> VersionInfo:
    """FastAPI dependency to inject version info into route handlers."""
    return get_api_version(request)


__all__ = [
    "APIVersion",
    "VersionConfig",
    "VersionInfo",
    "VersionNegotiator",
    "VersioningMiddleware",
    "include_versioned_routes",
    "version_config",
    "version_negotiator",
    "create_versioning_middleware",
    "get_api_version",
    "api_version_dependency",
]