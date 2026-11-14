"""Read-only connector for the authenticated user's SeoulTech e-Class data."""

from .client import SeoultechLMSClient

__version__ = "0.1.0"

__all__ = ["SeoultechLMSClient", "__version__"]
