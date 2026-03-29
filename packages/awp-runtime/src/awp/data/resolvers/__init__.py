"""Built-in source resolvers — auto-registered on import."""

from awp.data.resolvers.api_resolver import ApiResolver
from awp.data.resolvers.base64_resolver import Base64Resolver
from awp.data.resolvers.clipboard_resolver import ClipboardResolver
from awp.data.resolvers.glob_resolver import GlobResolver
from awp.data.resolvers.s3_resolver import S3Resolver
from awp.data.resolvers.sql_resolver import SqlResolver
from awp.data.resolvers.url_resolver import UrlResolver
from awp.data.sources import register_resolver

# Register all built-in resolvers
register_resolver(UrlResolver())
register_resolver(SqlResolver())
register_resolver(S3Resolver())
register_resolver(GlobResolver())
register_resolver(ApiResolver())
register_resolver(Base64Resolver())
register_resolver(ClipboardResolver())

__all__ = [
    "UrlResolver",
    "SqlResolver",
    "S3Resolver",
    "GlobResolver",
    "ApiResolver",
    "Base64Resolver",
    "ClipboardResolver",
]
