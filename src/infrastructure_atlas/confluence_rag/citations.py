import re
from difflib import SequenceMatcher
from infrastructure_atlas.confluence_rag.models import Chunk, Citation, ConfluencePage

class CitationExtractor:
    """
    Extracts quotable passages from search results.
    """
    
    CONTEXT_CHARS = 100  # Characters of context before/after quote
    
    def extract_citations(
        self,
        chunk: Chunk,
        page: ConfluencePage,
        query: str,
        relevance_score: float
    ) -> list[Citation]:
        """
        Extract quotable passages from a chunk.
        """
        citations = []
        
        # Find relevant sentences in the original content
        sentences = self._extract_sentences(chunk.original_content)
        
        for sentence in sentences:
            if self._is_quotable(sentence, query):
                # Determine context
                context_before, context_after = self._get_context(
                    chunk.original_content,
                    sentence
                )
                
                # Determine section
                section = self._determine_section(chunk, page)
                
                citations.append(Citation(
                    quote=sentence,
                    page_title=page.title,
                    page_url=self._build_page_url(page, chunk),
                    space_key=page.space_key,
                    section=section,
                    context_before=context_before,
                    context_after=context_after,
                    chunk_id=chunk.chunk_id,
                    confidence_score=self._calculate_confidence(
                        sentence, query, relevance_score
                    )
                ))
        
        # Sort by confidence and return top quotes
        citations.sort(key=lambda c: c.confidence_score, reverse=True)
        return citations[:3]  # Max 3 quotes per chunk
    
    def _extract_sentences(self, text: str) -> list[str]:
        """Extract sentences from text"""
        # Preserve original formatting for exact quotes
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if len(s.strip()) > 20]
    
    def _is_quotable(self, sentence: str, query: str) -> bool:
        """Determine if a sentence is quotable for this query"""
        # Check for informative content
        if len(sentence) < 30 or len(sentence) > 500:
            return False
        
        # Check for relevance with query
        query_terms = set(query.lower().split())
        sentence_terms = set(sentence.lower().split())
        # Remove common stop words for basic overlap check
        stop_words = {"a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or", "is", "are"}
        query_terms = query_terms - stop_words
        
        overlap = len(query_terms & sentence_terms)
        
        return overlap > 0 or self._semantic_match(sentence, query) > 0.3
    
    def _semantic_match(self, sentence: str, query: str) -> float:
        """Simple semantic similarity without embeddings"""
        return SequenceMatcher(
            None, 
            sentence.lower(), 
            query.lower()
        ).ratio()
    
    def _get_context(self, full_text: str, quote: str) -> tuple[str, str]:
        """Get context before and after the quote"""
        idx = full_text.find(quote)
        if idx == -1:
            return "", ""
        
        # Context before quote
        start = max(0, idx - self.CONTEXT_CHARS)
        context_before = full_text[start:idx].strip()
        if start > 0:
            context_before = "..." + context_before
        
        # Context after quote
        end = min(len(full_text), idx + len(quote) + self.CONTEXT_CHARS)
        context_after = full_text[idx + len(quote):end].strip()
        if end < len(full_text):
            context_after = context_after + "..."
        
        return context_before, context_after
    
    def _determine_section(self, chunk: Chunk, page: ConfluencePage) -> str | None:
        """Determine the section name for the citation"""
        if chunk.heading_context:
            return chunk.heading_context
        
        if len(chunk.context_path) > 2:
            return chunk.context_path[-1]
        
        return None
    
    def _build_page_url(self, page: ConfluencePage, chunk: Chunk) -> str:
        """Build URL with anchor to section if possible"""
        base_url = page.url
        
        if chunk.heading_context:
            # Confluence anchor format: space replace with hyphen, lower case
            # This is a rough approximation, Confluence anchors can be more complex
            anchor = chunk.heading_context.lower().replace(' ', '-')
            # Remove special chars
            anchor = re.sub(r'[^a-z0-9\-]', '', anchor)
            return f"{base_url}#{anchor}"
        
        return base_url
    
    def _calculate_confidence(
        self, 
        sentence: str, 
        query: str, 
        chunk_relevance: float
    ) -> float:
        """Calculate confidence score for a citation"""
        # Combine chunk relevance with sentence-level matching
        sentence_match = self._semantic_match(sentence, query)
        
        # Bonus for informative sentences
        informativeness = min(len(sentence) / 200, 1.0)
        
        return (chunk_relevance * 0.5 + sentence_match * 0.3 + informativeness * 0.2)

    def format_citation_markdown(self, citation: Citation) -> str:
        """Format a citation as markdown for output"""
        return (
            f'> "{citation.quote}"\n'
            f'> \n'
            f'> — [{citation.page_title}]({citation.page_url})'
            f'{f" § {citation.section}" if citation.section else ""}'
        )
    
    def format_citation_structured(self, citation: Citation) -> dict:
        """Format citation for API response"""
        return {
            "quote": citation.quote,
            "source": {
                "title": citation.page_title,
                "url": citation.page_url,
                "space": citation.space_key,
                "section": citation.section
            },
            "context": {
                "before": citation.context_before,
                "after": citation.context_after
            },
            "confidence": round(citation.confidence_score, 3)
        }
