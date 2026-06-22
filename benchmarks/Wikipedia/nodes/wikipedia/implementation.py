import logging
import wikipediaapi
import requests
import functools
from typing import Dict, List, Optional, Any
from atsuite_sdk.abstract import registry

logger = logging.getLogger(__name__)

# =============================
# Original Implementation
# Wikipedia MCP Server
# https://github.com/rudra-ravi/wikipedia-mcp
# =============================


class WikipediaClient:
    """Client for interacting with the Wikipedia API."""

    LANGUAGE_VARIANTS = {
        'zh-hans': 'zh',
        'zh-hant': 'zh',
        'zh-tw': 'zh',
        'zh-hk': 'zh',
        'zh-mo': 'zh',
        'zh-cn': 'zh',
        'zh-sg': 'zh',
        'zh-my': 'zh',
        'sr-latn': 'sr',
        'sr-cyrl': 'sr',
        'no': 'nb',
        'ku-latn': 'ku',
        'ku-arab': 'ku',
    }

    def __init__(self, language: str = "en", enable_cache: bool = False):
        self.original_language = language
        self.enable_cache = enable_cache
        self.user_agent = "WikipediaMCPServer/0.1.0 (https://github.com/rudra-ravi/wikipedia-mcp)"
        
        self.base_language, self.language_variant = self._parse_language_variant(language)
        self.headers = {
            "User-Agent": "atsuite-mcp/1.0 (research tool)"
        }
        
        self.wiki = wikipediaapi.Wikipedia(
            user_agent=self.user_agent,
            language=self.base_language,
            extract_format=wikipediaapi.ExtractFormat.WIKI
        )
        self.api_url = f"https://{self.base_language}.wikipedia.org/w/api.php"
        
        if self.enable_cache:
            self.search = functools.lru_cache(maxsize=128)(self.search)
            self.get_article = functools.lru_cache(maxsize=128)(self.get_article)
            self.get_summary = functools.lru_cache(maxsize=128)(self.get_summary)
            self.get_sections = functools.lru_cache(maxsize=128)(self.get_sections)
            self.get_links = functools.lru_cache(maxsize=128)(self.get_links)
            self.get_related_topics = functools.lru_cache(maxsize=128)(self.get_related_topics)
            self.summarize_for_query = functools.lru_cache(maxsize=128)(self.summarize_for_query)
            self.summarize_section = functools.lru_cache(maxsize=128)(self.summarize_section)
            self.extract_facts = functools.lru_cache(maxsize=128)(self.extract_facts)

    def _parse_language_variant(self, language: str) -> tuple:
        if language in self.LANGUAGE_VARIANTS:
            base_language = self.LANGUAGE_VARIANTS[language]
            return base_language, language
        else:
            return language, None
    
    def _add_variant_to_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if self.language_variant:
            params = params.copy()
            params['variant'] = self.language_variant
        return params

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        params = {
            'action': 'query',
            'format': 'json',
            'list': 'search',
            'utf8': 1,
            'srsearch': query,
            'srlimit': limit
        }
        
        params = self._add_variant_to_params(params)
        
        try:
            response = requests.get(self.api_url, params=params, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get('query', {}).get('search', []):
                results.append({
                    'title': item.get('title', ''),
                    'snippet': item.get('snippet', ''),
                    'pageid': item.get('pageid', 0),
                    'wordcount': item.get('wordcount', 0),
                    'timestamp': item.get('timestamp', '')
                })
            
            return results
        except Exception as e:
            logger.error(f"Error searching Wikipedia: {e}")
            return []

    def get_article(self, title: str) -> Dict[str, Any]:
        try:
            page = self.wiki.page(title)
            
            if not page.exists():
                return {
                    'title': title,
                    'exists': False,
                    'error': 'Page does not exist'
                }
            
            sections = self._extract_sections(page.sections)
            categories = [cat for cat in page.categories.keys()]
            links = [link for link in page.links.keys()]
            
            return {
                'title': page.title,
                'pageid': page.pageid,
                'summary': page.summary,
                'text': page.text,
                'url': page.fullurl,
                'sections': sections,
                'categories': categories,
                'links': links[:100],
                'exists': True
            }
        except Exception as e:
            logger.error(f"Error getting Wikipedia article: {e}")
            return {
                'title': title,
                'exists': False,
                'error': str(e)
            }

    def get_summary(self, title: str) -> str:
        try:
            page = self.wiki.page(title)
            
            if not page.exists():
                return f"No Wikipedia article found for '{title}'."
            
            return page.summary
        except Exception as e:
            logger.error(f"Error getting Wikipedia summary: {e}")
            return f"Error retrieving summary for '{title}': {str(e)}"

    def get_sections(self, title: str) -> List[Dict[str, Any]]:
        try:
            page = self.wiki.page(title)
            
            if not page.exists():
                return []
            
            return self._extract_sections(page.sections)
        except Exception as e:
            logger.error(f"Error getting Wikipedia sections: {e}")
            return []

    def get_links(self, title: str) -> List[str]:
        try:
            page = self.wiki.page(title)
            
            if not page.exists():
                return []
            
            return [link for link in page.links.keys()]
        except Exception as e:
            logger.error(f"Error getting Wikipedia links: {e}")
            return []

    def get_related_topics(self, title: str, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            page = self.wiki.page(title)
            
            if not page.exists():
                return []
            
            links = list(page.links.keys())
            categories = list(page.categories.keys())
            
            related = []
            
            for link in links[:limit]:
                link_page = self.wiki.page(link)
                if link_page.exists():
                    related.append({
                        'title': link,
                        'summary': link_page.summary[:200] + '...' if len(link_page.summary) > 200 else link_page.summary,
                        'url': link_page.fullurl,
                        'type': 'link'
                    })
                
                if len(related) >= limit:
                    break
            
            remaining = limit - len(related)
            if remaining > 0:
                for category in categories[:remaining]:
                    clean_category = category.replace("Category:", "")
                    related.append({
                        'title': clean_category,
                        'type': 'category'
                    })
            
            return related
        except Exception as e:
            logger.error(f"Error getting related topics: {e}")
            return []

    def _extract_sections(self, sections, level=0) -> List[Dict[str, Any]]:
        result = []
        
        for section in sections:
            section_data = {
                'title': section.title,
                'level': level,
                'text': section.text,
                'sections': self._extract_sections(section.sections, level + 1)
            }
            result.append(section_data)
        
        return result

    def summarize_for_query(self, title: str, query: str, max_length: int = 250) -> str:
        try:
            page = self.wiki.page(title)
            if not page.exists():
                return f"No Wikipedia article found for '{title}'."

            text_content = page.text
            query_lower = query.lower()
            text_lower = text_content.lower()

            start_index = text_lower.find(query_lower)
            if start_index == -1:
                summary_part = page.summary[:max_length]
                if not summary_part:
                    summary_part = text_content[:max_length]
                return summary_part + "..." if len(summary_part) >= max_length else summary_part

            context_start = max(0, start_index - (max_length // 2))
            context_end = min(len(text_content), start_index + len(query) + (max_length // 2))
            
            snippet = text_content[context_start:context_end]
            
            if len(snippet) > max_length:
                snippet = snippet[:max_length]

            return snippet + "..." if len(snippet) >= max_length or context_end < len(text_content) else snippet

        except Exception as e:
            logger.error(f"Error generating query-focused summary for '{title}': {e}")
            return f"Error generating query-focused summary for '{title}': {str(e)}"

    def summarize_section(self, title: str, section_title: str, max_length: int = 150) -> str:
        try:
            page = self.wiki.page(title)
            if not page.exists():
                return f"No Wikipedia article found for '{title}'."

            def find_section_recursive(sections_list, target_title):
                for sec in sections_list:
                    if sec.title.lower() == target_title.lower():
                        return sec
                    found_in_subsection = find_section_recursive(sec.sections, target_title)
                    if found_in_subsection:
                        return found_in_subsection
                return None

            target_section = find_section_recursive(page.sections, section_title)

            if not target_section or not target_section.text:
                return f"Section '{section_title}' not found or is empty in article '{title}'."
            
            summary = target_section.text[:max_length]
            return summary + "..." if len(target_section.text) > max_length else summary
            
        except Exception as e:
            logger.error(f"Error summarizing section '{section_title}' for article '{title}': {e}")
            return f"Error summarizing section '{section_title}': {str(e)}"

    def extract_facts(self, title: str, topic_within_article: Optional[str] = None, count: int = 5) -> List[str]:
        try:
            page = self.wiki.page(title)
            if not page.exists():
                return [f"No Wikipedia article found for '{title}'."]

            text_to_process = ""
            if topic_within_article:
                def find_section_text_recursive(sections_list, target_title):
                    for sec in sections_list:
                        if sec.title.lower() == target_title.lower():
                            return sec.text
                        found_in_subsection = find_section_text_recursive(sec.sections, target_title)
                        if found_in_subsection:
                            return found_in_subsection
                    return None
                
                section_text = find_section_text_recursive(page.sections, topic_within_article)
                if section_text:
                    text_to_process = section_text
                else:
                    text_to_process = page.summary
            else:
                text_to_process = page.summary
            
            if not text_to_process:
                return ["No content found to extract facts from."]

            sentences = [s.strip() for s in text_to_process.split('.') if s.strip()]
            
            facts = []
            for sentence in sentences[:count]:
                if sentence:
                    facts.append(sentence + ".")
            
            return facts if facts else ["Could not extract facts from the provided text."]

        except Exception as e:
            logger.error(f"Error extracting key facts for '{title}': {e}")
            return [f"Error extracting key facts for '{title}': {str(e)}"]


# =============================
# Definitions for Agent Tools
# =============================

wikipedia_client = WikipediaClient()

@registry.tool()
def wikipedia_search(query: str, limit: int = 10) -> Dict[str, Any]:
    """Search Wikipedia for articles matching a query."""
    results = wikipedia_client.search(query, limit=limit)
    return {
        "query": query,
        "results": results
    }

@registry.tool()
def wikipedia_get_article(title: str) -> Dict[str, Any]:
    """Get the full content of a Wikipedia article."""
    return wikipedia_client.get_article(title)

@registry.tool()
def wikipedia_get_summary(title: str) -> Dict[str, Any]:
    """Get a summary of a Wikipedia article."""
    summary = wikipedia_client.get_summary(title)
    return {
        "title": title,
        "summary": summary
    }

@registry.tool()
def wikipedia_summarize_article_for_query(title: str, query: str, max_length: int = 250) -> Dict[str, Any]:
    """Get a summary of a Wikipedia article tailored to a specific query."""
    summary = wikipedia_client.summarize_for_query(title, query, max_length=max_length)
    return {
        "title": title,
        "query": query,
        "summary": summary
    }

@registry.tool()
def wikipedia_summarize_article_section(title: str, section_title: str, max_length: int = 150) -> Dict[str, Any]:
    """Get a summary of a specific section of a Wikipedia article."""
    summary = wikipedia_client.summarize_section(title, section_title, max_length=max_length)
    return {
        "title": title,
        "section_title": section_title,
        "summary": summary
    }

@registry.tool()
def wikipedia_extract_key_facts(title: str, topic_within_article: str = "", count: int = 5) -> Dict[str, Any]:
    """Extract key facts from a Wikipedia article, optionally focused on a topic."""
    topic = topic_within_article if topic_within_article.strip() else None
    facts = wikipedia_client.extract_facts(title, topic, count=count)
    return {
        "title": title,
        "topic_within_article": topic_within_article,
        "facts": facts
    }

@registry.tool()
def wikipedia_get_related_topics(title: str, limit: int = 10) -> Dict[str, Any]:
    """Get topics related to a Wikipedia article based on links and categories."""
    related = wikipedia_client.get_related_topics(title, limit=limit)
    return {
        "title": title,
        "related_topics": related
    }

@registry.tool()
def wikipedia_get_sections(title: str) -> Dict[str, Any]:
    """Get the sections of a Wikipedia article."""
    sections = wikipedia_client.get_sections(title)
    return {
        "title": title,
        "sections": sections
    }

@registry.tool()
def wikipedia_get_links(title: str) -> Dict[str, Any]:
    """Get the links contained within a Wikipedia article."""
    links = wikipedia_client.get_links(title)
    return {
        "title": title,
        "links": links
    }
