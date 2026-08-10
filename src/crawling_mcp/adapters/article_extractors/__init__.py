"""Site-aware article extraction adapters."""

from crawling_mcp.adapters.article_extractors.registry import ArticleExtractorRegistry
from crawling_mcp.adapters.article_extractors.structured import StructuredArticleExtractor

__all__ = ["ArticleExtractorRegistry", "StructuredArticleExtractor"]
