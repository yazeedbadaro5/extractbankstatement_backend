import io
from typing import Optional
import fitz  # PyMuPDF
from src.utils.logger import get_logger

logger = get_logger(__name__)


def count_pdf_pages(file_bytes: bytes) -> Optional[int]:
    """
    Quickly count the number of pages in a PDF file.
    
    Args:
        file_bytes: PDF file content as bytes
        
    Returns:
        Number of pages or None if error
    """
    try:
        pdf_stream = io.BytesIO(file_bytes)
        pdf_doc = fitz.open(stream=pdf_stream, filetype="pdf")
        page_count = pdf_doc.page_count
        pdf_doc.close()
        
        logger.info(f"PDF contains {page_count} pages")
        return page_count
        
    except Exception as e:
        logger.error(f"Failed to count PDF pages: {e}")
        return None
