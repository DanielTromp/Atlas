import logging
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

# Configure logging
logging.basicConfig(level=logging.INFO)

from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker
from infrastructure_atlas.confluence_rag.models import ConfluencePage
from docling.datamodel.base_models import InputFormat

def test_chunker():
    print("Starting chunker test...")
    
    chunker = ConfluenceChunker()
    
    html = """
    <h1>Test Page</h1>
    <p>This is a paragraph with some content.</p>
    <h2>Section 1</h2>
    <p>This is another paragraph.</p>
    <pre><code>print("Hello World")</code></pre>
    """
    
    raw = "Test Page\nThis is a paragraph with some content.\nSection 1\nThis is another paragraph.\nprint(\"Hello World\")"
    
    from datetime import datetime
    page = ConfluencePage(
        page_id="123",
        space_key="TEST",
        title="Test Page",
        url="http://example.com",
        labels=[],
        version=1,
        updated_at=datetime.utcnow(),
        updated_by="User",
        parent_id=None,
        ancestors=[]
    )
    
    print("Calling chunk_page...")
    
    res = chunker.converter.convert_string(html, format=InputFormat.HTML)
    doc = res.document
    print(f"Docling Document attributes: {dir(doc)}")
    
    print("-" * 20)
    print("Iterating items manually:")
    count = 0
    for item in doc.iterate_items():
        count += 1
        print(f"Item {count}: type={type(item)}")
        print(f"  value: {item}")
        # print(f"  text: {getattr(item, 'text', 'N/A')}")
        # print(f"  label: {getattr(item, 'label', 'N/A')}")
        if count >= 3: break
    print(f"Total items: {count} (stopped printing after 3)")
    print("-" * 20)
    
    chunks = chunker.chunk_page(page, html, raw)
    
    print(f"Generated {len(chunks)} chunks")
    for c in chunks:
        print(f"[{c.chunk_type.value}] {c.content[:50]}...")

if __name__ == "__main__":
    test_chunker()
