"""Site-aware article extraction adapters."""

from crawling_mcp.adapters.outbound.extraction.articles.registry import ArticleExtractorRegistry
from crawling_mcp.adapters.outbound.extraction.articles.structured import StructuredArticleExtractor

__all__ = ["ArticleExtractorRegistry", "StructuredArticleExtractor"]
