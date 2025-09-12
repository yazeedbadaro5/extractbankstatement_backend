import io
import json
import time
import base64
import asyncio
import pandas as pd
import os
import tempfile
import warnings
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

# PDF to image conversion
import fitz  # PyMuPDF
from PIL import Image

# LangChain imports
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

# Retry handling
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_exception

from src.configuration.config import settings
from src.utils.logger import get_logger
from src.services.task_manager import task_manager, TaskStatus

# Configure gRPC and TensorFlow to suppress verbose logging
os.environ['GRPC_VERBOSITY'] = 'NONE'
os.environ['GRPC_TRACE'] = ''
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['GLOG_minloglevel'] = '3'
os.environ['ABSL_MIN_LOG_LEVEL'] = '3'
os.environ['GRPC_ENABLE_FORK_SUPPORT'] = '1'

# Override LangChain's default timeout settings
os.environ['LANGCHAIN_TRACING_V2'] = 'false'  # Disable tracing to avoid extra timeouts

# Suppress all warnings including gRPC fork warnings
warnings.filterwarnings("ignore")

# Suppress TensorFlow and other ML library warnings
logging.getLogger('tensorflow').setLevel(logging.CRITICAL)
logging.getLogger('absl').setLevel(logging.CRITICAL)
logging.getLogger('grpc').setLevel(logging.CRITICAL)

logger = get_logger(__name__)


class RetryableAPIError(Exception):
    """Exception for API errors that should be retried"""
    pass

class IntentionalEmptyResultError(Exception):
    """Exception for when the AI intentionally returns empty results (should not retry)"""
    pass


def is_retryable_error(exception):
    """Determine if an error should be retried"""
    error_msg = str(exception).lower()
    
    # Retry on these types of errors
    retryable_patterns = [
        "500 an internal error has occurred",
        "503 service unavailable", 
        "502 bad gateway",
        "504 gateway timeout",
        "connection error",
        "timeout",
        "rate limit",
        "quota exceeded"
    ]
    
    return any(pattern in error_msg for pattern in retryable_patterns)


class TableRow(BaseModel):
    """Represents a single row in a bank statement table"""
    data: Dict[str, Any] = Field(description="Dictionary containing column names as keys and cell values as values")


class TableData(BaseModel):
    """Represents the extracted table data from a bank statement page"""
    table_data: List[Dict[str, Any]] = Field(description="List of dictionaries, each representing a row with column names as keys")

class ColumnSchema(BaseModel):
    """Represents the column schema extracted from a bank statement"""
    columns: List[str] = Field(description="List of column names exactly as they appear in the bank statement")

class StandardizedColumns(BaseModel):
    """Represents the final standardized column names for consistent extraction"""
    final_columns: List[str] = Field(description="Final standardized column names to use for all extractions")


class UniversalPDFExtractionService:
    """Simple async PDF extraction service - no multiprocessing, clean event loop"""
    
    def __init__(self):
        # Don't create LLM instance here - create fresh ones for each batch
        pass
    
    def create_llm(self):
        """Create a fresh LLM instance for each batch to avoid gRPC connection conflicts"""
        return ChatGoogleGenerativeAI(
            model="gemini-2.5-pro-preview-03-25",
            google_api_key=settings.gemini_api_key,
            temperature=0,
            max_retries=0,  # Let Tenacity handle all retries
            timeout=90,  # Set explicit timeout parameter
            request_timeout=90  # Also set request_timeout for compatibility
        )

    async def extract_bank_statement(self, file_bytes: bytes, filename: str, required_columns: Optional[List[str]] = None, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Extract bank statement data using three-phase approach for consistent column names"""
        logger.info(f"Starting three-phase table extraction for {filename}")

        try:
            start_time = time.time()
            
            # Get all pages from PDF
            pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
            total_pages = len(pdf_document)
            pdf_document.close()
            
            logger.info(f"Processing {total_pages} pages with three-phase extraction")
            
            # PHASE 1: Extract column names from sample pages
            if task_id:
                task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Analyzing column structure...", 5)
            
            raw_columns = await self.extract_column_schema_from_sample(file_bytes, total_pages, task_id)
            
            # PHASE 2: Standardize column names using LLM
            if task_id:
                task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Standardizing column names...", 8)
                
            standardized_columns = await self.standardize_column_names(raw_columns)
            
            logger.info(f"Using standardized columns for extraction: {standardized_columns}")
            
            # PHASE 3: Extract tables from each page using standardized column names
            if task_id:
                task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Extracting tables with consistent columns...", 10)
            
            all_tables = await self.extract_bank_statement_async_batching(
                file_bytes, total_pages, standardized_columns, task_id
            )
            
            if not all_tables:
                logger.warning("No tables extracted from any pages")
                return {"success": False, "error": "No tables extracted"}
            
            # Combine all tables
            combined_table = await self.combine_tables(all_tables)
            
            # Create Excel file
            excel_path = await self.create_excel_file(combined_table, filename)
            
            end_time = time.time()
            logger.info(f"Total extraction time: {end_time - start_time:.2f} seconds")
            
            return {
                "success": True,
                "filename": filename,
                "excel_path": excel_path,
                "total_rows": len(combined_table) if combined_table is not None else 0,
                "columns": list(combined_table.columns) if combined_table is not None else [],
                "processing_time": end_time - start_time
            }
            
        except Exception as e:
            logger.error(f"Error extracting tables from {filename}: {e}")
            return {"success": False, "error": str(e)}
    
    async def extract_bank_statement_async_batching(self, file_bytes: bytes, total_pages: int, 
                                           required_columns: Optional[List[str]], task_id: Optional[str] = None) -> List[Dict]:
        """Extract tables using simple async batching - no multiprocessing, no nested event loops"""
        logger.info(f"Extracting tables from {total_pages} pages using async batching")
        
        # Dynamic batch size based on PDF size for optimal performance
        if total_pages <= 5:
            batch_size = total_pages  # Small PDFs: 1 batch
            logger.info(f"Small PDF ({total_pages} pages): using 1 batch")
        elif total_pages <= 15:
            batch_size = 5  # Medium PDFs: 5 pages per batch
            logger.info(f"Medium PDF ({total_pages} pages): using {batch_size} pages per batch")
        elif total_pages <= 30:
            batch_size = 4  # Large PDFs: 4 pages per batch
            logger.info(f"Large PDF ({total_pages} pages): using {batch_size} pages per batch")
        elif total_pages <= 50:
            batch_size = 3  # Very large PDFs: 3 pages per batch
            logger.info(f"Very large PDF ({total_pages} pages): using {batch_size} pages per batch")
        else:
            batch_size = 2  # Huge PDFs: 2 pages per batch for stability
            logger.info(f"Huge PDF ({total_pages} pages): using {batch_size} pages per batch for stability")
        
        # Create batches of page numbers
        page_batches = []
        for i in range(0, total_pages, batch_size):
            batch_pages = list(range(i + 1, min(i + batch_size + 1, total_pages + 1)))  # Pages are 1-indexed
            page_batches.append(batch_pages)
        
        logger.info(f"Processing {len(page_batches)} batches of ~{batch_size} pages each")
        
        # Create a shared counter for completed pages (thread-safe)
        import threading
        completed_pages_lock = threading.Lock()
        completed_pages_count = [0]  # Use list to make it mutable in closure
        
        # Create semaphore to limit concurrent API calls (max 150 batches at once)
        semaphore = asyncio.Semaphore(150)
        logger.info(f"Using semaphore to limit to 150 concurrent batches (out of {len(page_batches)} total)")
        
        # Create async tasks for each batch with semaphore control
        batch_tasks = []
        for i, page_numbers in enumerate(page_batches):
            task = self._process_batch_with_semaphore(
                semaphore, file_bytes, page_numbers, required_columns, task_id, 
                completed_pages_lock, completed_pages_count, total_pages
            )
            batch_tasks.append(task)
        
        # Execute all batches with controlled concurrency
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        
        # Collect successful results
        all_results = []
        pages_completed = 0
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.error(f"Error processing batch {i}: {result}")
                continue
            if result:
                all_results.extend(result)
                pages_completed += len(result)
        
        logger.info(f"Async extraction completed. Total results: {len(all_results)}")
        return all_results

    async def _process_batch_with_semaphore(self, semaphore: asyncio.Semaphore, file_bytes: bytes, 
                                           page_numbers: List[int], required_columns: Optional[List[str]], 
                                           task_id: Optional[str], completed_pages_lock, 
                                           completed_pages_count: List[int], total_pages: int) -> List[Dict]:
        """Process a batch with semaphore to control concurrency"""
        async with semaphore:
            # Only 30 batches can run this block simultaneously
            return await self.process_page_batch_simple(
                file_bytes, page_numbers, required_columns, task_id,
                completed_pages_lock, completed_pages_count, total_pages
            )

    async def process_page_batch_simple(self, file_bytes: bytes, page_numbers: List[int], 
                                       required_columns: Optional[List[str]], task_id: Optional[str],
                                       completed_pages_lock, completed_pages_count: List[int], total_pages: int) -> List[Dict]:
        """Process a batch of pages sequentially within this async function"""
        logger.info(f"Processing batch with pages {page_numbers}")
        
        # Create a fresh LLM instance for this batch to avoid gRPC connection conflicts
        llm = self.create_llm()
        batch_results = []
        
        try:
            # Process each page in the batch sequentially (but batches run concurrently)
            for page_num in page_numbers:
                try:
                    # Extract page as image bytes for vision processing
                    pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
                    page = pdf_document.load_page(page_num - 1)  # fitz uses 0-based indexing
                    
                    # Convert page to high-quality image
                    pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))  # 2x resolution for better OCR
                    page_image_bytes = pix.tobytes("png")
                    pdf_document.close()
                    
                    if len(page_image_bytes) == 0:
                        logger.warning(f"Page {page_num} appears to be empty, skipping")
                        continue
                    
                    # Use the LLM to extract table data from this page image
                    try:
                        result = await self.extract_table_from_page_image(llm, page_image_bytes, page_num, required_columns)
                    except IntentionalEmptyResultError:
                        logger.info(f"Page {page_num}: Intentionally empty - skipping")
                        result = None
                    except RetryableAPIError as e:
                        logger.error(f"Page {page_num}: API error persisted after 3 retries: {e}")
                        result = None
                    
                    if result and result.get('table_data'):
                        # Convert to the expected format
                        df = pd.DataFrame(result['table_data'])
                        batch_results.append({
                            'dataframe': df,
                            'page_number': page_num,
                            'metadata': {}
                        })
                        logger.info(f"✅ Page {page_num}: Found {len(result.get('table_data', []))} rows")
                    else:
                        logger.info(f"⚠️ Page {page_num}: No table data found")
                    
                    # Update progress after each page completion
                    if task_id:
                        with completed_pages_lock:
                            completed_pages_count[0] += 1
                            current_completed = completed_pages_count[0]
                        
                        progress = min(95, 20 + (current_completed / total_pages) * 70)
                        task_manager.update_task_status(
                            task_id, 
                            TaskStatus.PROCESSING, 
                            f"Processed {current_completed}/{total_pages} pages", 
                            progress
                        )
                        
                except Exception as e:
                    logger.error(f"❌ Error processing page {page_num}: {e}")
                    
                    # Still update progress even for failed pages
                    if task_id:
                        with completed_pages_lock:
                            completed_pages_count[0] += 1
                            current_completed = completed_pages_count[0]
                        
                        progress = min(95, 20 + (current_completed / total_pages) * 70)
                        task_manager.update_task_status(
                            task_id, 
                            TaskStatus.PROCESSING, 
                            f"Processed {current_completed}/{total_pages} pages", 
                            progress
                        )
                    continue
                    
        finally:
            # Clean up LLM resources to prevent pending task warnings
            try:
                if hasattr(llm, 'client') and hasattr(llm.client, 'close'):
                    await llm.client.close()
                elif hasattr(llm, '_client') and hasattr(llm._client, 'close'):
                    await llm._client.close()
            except Exception:
                pass  # Ignore cleanup errors
        
        logger.info(f"Batch with pages {page_numbers} completed with {len(batch_results)} successful pages")
        return batch_results

    async def extract_table_from_page_image(self, llm, page_image_bytes: bytes, page_num: int, 
                                           required_columns: Optional[List[str]]) -> Optional[Dict]:
        """Extract table data from page image using LLM with vision capabilities"""
        return await self._extract_with_retry_vision(llm, page_image_bytes, page_num, required_columns)
    
    @retry(
        retry=retry_if_exception(lambda e: not isinstance(e, IntentionalEmptyResultError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),  # 2s → 4s → 8s delays
        reraise=True
    )
    async def _extract_with_retry_vision(self, llm, page_image_bytes: bytes, page_num: int, 
                                        required_columns: Optional[List[str]]) -> Optional[Dict]:
        """Internal method with retry logic for vision-based API errors"""
        try:
            # Create the JSON output parser
            parser = JsonOutputParser(pydantic_object=TableData)
            
            # Include format instructions from the parser
            format_instructions = parser.get_format_instructions()
            
            # Modern 2025 vision prompt with Chain of Thought
            prompt_text = f"""You are an expert financial data analyst specializing in bank statement processing. Your task is to extract transaction data from this bank statement page image with perfect accuracy and consistency.

## EXTRACTION CONTEXT AND REQUIREMENTS

**Document Type**: Bank Statement Page {page_num}
**Task**: Extract all financial transactions into structured JSON format
**REQUIRED COLUMNS (EXACT NAMES)**: {', '.join(required_columns) if required_columns else 'All available transaction fields'}

## CRITICAL COLUMN MAPPING REQUIREMENT

🔴 **USE EXACT COLUMN NAMES FROM REQUIRED LIST ABOVE**
- You MUST use the exact column names provided in "REQUIRED COLUMNS" 
- Do NOT create new column names or variations
- Map the visual columns in the image to the required column names
- If a visual column doesn't match any required column, skip it
- If a required column is not visible on this page, omit it from the result

## STEP-BY-STEP VISUAL ANALYSIS PROCESS

1. **Image Scan**: Examine the entire page for tables, transaction rows, and financial data
2. **Layout Analysis**: Identify table boundaries, column headers, and row separations
3. **Text Recognition**: Read all text carefully, including numbers, dates, and descriptions
4. **Structure Mapping**: Map visual table structure to data relationships
5. **Data Extraction**: Extract each transaction row systematically
6. **Quality Check**: Verify all amounts, dates, and descriptions are captured correctly

## CRITICAL COLUMN NAME AND TEXT REQUIREMENTS

🔴 **EXTREMELY IMPORTANT - EXACT TEXT EXTRACTION RULES:**
- **NEVER TRANSLATE ANYTHING** - extract text EXACTLY as it appears in the original document
- **NO CHARACTER SUBSTITUTION** - never replace characters with similar-looking ones from other alphabets (e.g., do NOT replace Arabic "د" with English "d")  
- **PRESERVE ORIGINAL SCRIPTS** - maintain exact Unicode characters for all languages (Arabic, English, French, Spanish, Chinese, etc.)
- **MULTILINGUAL TEXT**: Some columns/content may mix languages (e.g., "Balance/الرصيد", "Crédit/дебет") - preserve ALL languages exactly as shown
- **CASE SENSITIVITY**: Preserve exact capitalization, diacritics, and accents as shown
- **SCRIPT INTEGRITY**: Never mix character sets - if text is Arabic, keep all Arabic characters; if Cyrillic, keep all Cyrillic
- **SPACING & PUNCTUATION**: Keep exact spacing, punctuation, and special characters

## NUMERIC DATA FORMATTING REQUIREMENTS

🔢 **NUMBER EXTRACTION RULES:**
- **Monetary amounts**: Extract as pure numbers (e.g., "1,234.56" becomes 1234.56)
- **Remove currency symbols**: Strip SAR, $, €, etc. from numbers
- **Remove commas**: Convert "1,234.56" to 1234.56
- **Preserve decimals**: Keep decimal precision exactly as shown
- **Negative numbers**: Preserve negative signs or parentheses (e.g., -1234.56 or (1234.56))
- **Date columns**: Keep as text strings in original format
- **ID/Reference numbers**: Keep as text strings to preserve leading zeros

## COLUMN MAPPING GUIDELINES

- **Date fields**: Look for date columns (DD/MM/YYYY, MM-DD-YYYY formats) - keep as text
- **Amount fields**: Identify debit/credit columns - extract as pure numbers without currency symbols
- **Description**: Transaction details, payee names, reference information - keep as text
- **Balance**: Running balance columns - extract as pure numbers
- **Reference/ID**: Check numbers, transaction IDs, reference codes - keep as text

## VISUAL DATA QUALITY RULES

✅ **DO:**
- Examine every row in the table, even if partially visible
- Extract ALL text EXACTLY as it appears in the original script/language
- Convert numeric columns to actual numbers for Excel compatibility
- Read text character-by-character to maintain script integrity
- Handle multi-line descriptions by reading all text in original language
- Capture empty cells as null or empty strings
- Look for continuation indicators across page boundaries
- Preserve all Unicode characters, diacritics, and special symbols

❌ **DON'T:**
- Skip rows due to poor image quality or partial visibility
- Translate, transliterate, or modify any text in any way
- Replace characters with similar-looking ones from different alphabets
- Leave numbers as text strings if they should be numeric
- Merge separate transaction rows
- Add data not visible in the image
- Make assumptions about incomplete information
- Convert between different writing systems or scripts

## OUTPUT FORMAT SPECIFICATION

{format_instructions}

## CHAIN OF THOUGHT REASONING

Before providing your final JSON, analyze:
1. What table structure do I see in this image?
2. How many transaction rows are clearly visible?
3. What are the column headers and their EXACT text in original script/language (no character substitution)?
4. Which columns contain numbers that should be extracted as numeric values?
5. Are there any visual formatting challenges (blurred text, cut-off sections)?
6. Have I preserved all text in its original language and script without any translation or character substitution?
7. Have I captured all visible transaction data accurately with correct data types?

If no transaction data is visible in this image, return {{"table_data": []}}

## YOUR RESPONSE:

Analyze the bank statement page image step by step, then provide the extracted transaction data in the required JSON format."""
            
            # Convert image bytes to base64 for LangChain
            import base64
            image_base64 = base64.b64encode(page_image_bytes).decode('utf-8')
            
            # Create multimodal message with image and text
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                    }
                ]
            )
            
            # Make async call to LLM with vision using asyncio.timeout
            async with asyncio.timeout(90):
                response = await llm.ainvoke([message])
            
            if not response or not response.content:
                logger.warning(f"Page {page_num}: Empty response from LLM")
                return None
            
            # Use LangChain's JSON parser to parse the response
            try:
                result = parser.parse(response.content)
                return result
            except Exception as e:
                logger.error(f"Page {page_num}: Failed to parse LLM response with LangChain parser: {e}")
                # Fallback to manual JSON extraction if parser fails
                import re
                json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                        return result
                    except json.JSONDecodeError:
                        pass
                return None
                
        except Exception as e:
            # Check if this is a retryable error
            if is_retryable_error(e):
                logger.warning(f"Page {page_num}: Retryable API error encountered: {e}")
                raise RetryableAPIError(f"API error for page {page_num}: {e}") from e
            else:
                # Non-retryable error - log and return None
                logger.error(f"Page {page_num}: Non-retryable error in vision extraction: {e}")
                return None
    
    @retry(
        retry=retry_if_exception(lambda e: is_retryable_error(e)),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),  # 2s → 4s delays
        reraise=True
    )
    async def _extract_with_retry(self, llm, page_text: str, page_num: int, 
                                 required_columns: Optional[List[str]]) -> Optional[Dict]:
        """Internal method with retry logic for API errors"""
        try:
            # Create the JSON output parser
            parser = JsonOutputParser(pydantic_object=TableData)
            
            # Create the prompt for table extraction
            if required_columns:
                columns_instruction = f"Focus on extracting these specific columns: {', '.join(required_columns)}"
            else:
                columns_instruction = "Extract all available columns"
            
            # Include format instructions from the parser
            format_instructions = parser.get_format_instructions()
            
            # Modern 2025 prompt with Chain of Thought and comprehensive context
            prompt = f"""You are an expert financial data analyst specializing in bank statement processing. Your task is to extract transaction data from bank statement text with perfect accuracy and consistency.

                        ## EXTRACTION CONTEXT AND REQUIREMENTS

                        **Document Type**: Bank Statement Page {page_num}
                        **Task**: Extract all financial transactions into structured JSON format
                        **Required Columns**: {', '.join(required_columns) if required_columns else 'All available transaction fields'}

                        ## STEP-BY-STEP ANALYSIS PROCESS

                        1. **Document Scan**: First, identify if this page contains transaction data (tables, rows of financial data)
                        2. **Structure Analysis**: Examine the table structure, headers, and column organization
                        3. **Data Extraction**: Extract each transaction row systematically
                        4. **Validation**: Verify dates, amounts, and descriptions are properly captured
                        5. **Standardization**: Format all data consistently according to schema requirements

                        ## COLUMN MAPPING GUIDELINES

                        - **Date fields**: Standardize to consistent format (preserve original if unclear)
                        - **Amount fields**: Include currency symbols, preserve negative indicators, decimal precision
                        - **Description**: Capture full transaction descriptions, clean extra whitespace
                        - **Balance**: Extract running balances if available
                        - **Reference/ID**: Capture transaction IDs, check numbers, reference codes

                        ## DATA QUALITY RULES

                        ✅ **DO:**
                        - Extract every transaction row, even partial data
                        - Preserve original formatting for currency and dates
                        - Include column headers as keys in JSON objects  
                        - Handle multi-line descriptions by concatenating
                        - Capture empty cells as null or empty strings
                        - Maintain decimal precision for monetary values

                        ❌ **DON'T:**
                        - Skip rows due to formatting irregularities
                        - Modify or interpret financial amounts
                        - Merge separate transactions
                        - Add data not present in the source
                        - Convert currencies or recalculate balances

                        ## OUTPUT FORMAT SPECIFICATION

                        {format_instructions}

                        ## CHAIN OF THOUGHT REASONING

                        Before providing your final JSON, think through:
                        1. What table structure do I see?
                        2. How many transaction rows are present? 
                        3. What are the column headers/types?
                        4. Are there any formatting challenges?
                        5. Have I captured all available data accurately?

                        If no transaction data exists on this page, return {{"table_data": []}}

                        ## SOURCE TEXT TO ANALYZE:

                        {page_text}

                        ## YOUR RESPONSE:

                        Analyze the above text step by step, then provide the extracted data in the required JSON format."""
            
            # Make async call to LLM using asyncio.timeout
            async with asyncio.timeout(90):
                response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            if not response or not response.content:
                logger.warning(f"Page {page_num}: Empty response from LLM - retrying")
                raise RetryableAPIError(f"Empty response from LLM for page {page_num}")
            
            # Use LangChain's JSON parser to parse the response
            try:
                result = parser.parse(response.content)
                # Check if this is an intentional empty result
                if result and hasattr(result, 'table_data') and not result.table_data:
                    logger.info(f"Page {page_num}: AI intentionally returned empty table")
                    raise IntentionalEmptyResultError(f"AI returned empty table for page {page_num}")
                elif isinstance(result, dict) and 'table_data' in result and not result['table_data']:
                    logger.info(f"Page {page_num}: AI intentionally returned empty table")
                    raise IntentionalEmptyResultError(f"AI returned empty table for page {page_num}")
                return result
            except IntentionalEmptyResultError:
                # Re-raise so it's not retried
                raise
            except Exception as e:
                logger.error(f"Page {page_num}: Failed to parse LLM response: {e} - retrying")
                # Fallback to manual JSON extraction if parser fails
                import re
                json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
                if json_match:
                    try:
                        result_dict = json.loads(json_match.group())
                        # Check if manual parsing also shows empty
                        if 'table_data' in result_dict and not result_dict['table_data']:
                            logger.info(f"Page {page_num}: AI intentionally returned empty table")
                            raise IntentionalEmptyResultError(f"AI returned empty table for page {page_num}")
                        return result_dict
                    except json.JSONDecodeError:
                        pass
                # If we can't parse anything, retry this
                raise RetryableAPIError(f"Could not parse response for page {page_num}: {e}")
                
        except asyncio.TimeoutError:
            logger.error(f"Page {page_num}: Request timed out after 90 seconds - retrying")
            raise RetryableAPIError(f"Timeout error for page {page_num}") from None
        except IntentionalEmptyResultError:
            # Don't retry intentional empty results
            raise
        except Exception as e:
            # Retry ALL other errors (API errors, network errors, etc.)
            logger.warning(f"Page {page_num}: Error encountered - retrying: {type(e).__name__}: {e}")
            raise RetryableAPIError(f"Error for page {page_num}: {e}") from e

    async def extract_column_schema_from_sample(self, file_bytes: bytes, total_pages: int, task_id: Optional[str] = None) -> List[str]:
        """Phase 1: Extract column names from a sample of pages (first 10% or max 3 pages) concurrently"""
        sample_size = max(1, min(3, int(total_pages * 0.1)))  # 10% of pages, max 3, min 1
        logger.info(f"Extracting column schema from {sample_size} sample pages out of {total_pages} total pages (concurrent)")
        
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        all_columns = set()
        
        try:
            # Prepare all sample pages for concurrent processing
            sample_tasks = []
            for page_idx in range(sample_size):
                page = doc[page_idx]
                
                # Convert page to high-res image
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                page_image_bytes = pix.tobytes("png")
                
                if len(page_image_bytes) == 0:
                    continue
                
                # Create task for concurrent processing
                task = self._extract_columns_from_sample_page(page_image_bytes, page_idx + 1)
                sample_tasks.append(task)
            
            # Process all sample pages concurrently
            if sample_tasks:
                results = await asyncio.gather(*sample_tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.warning(f"Failed to extract columns from sample page {i + 1}: {result}")
                    elif result:
                        all_columns.update(result)
                        logger.info(f"Sample page {i + 1}: Found columns {result}")
                    
        finally:
            doc.close()
        
        unique_columns = list(all_columns)
        logger.info(f"Phase 1 complete: Found {len(unique_columns)} unique column names: {unique_columns}")
        return unique_columns

    async def _extract_columns_from_sample_page(self, page_image_bytes: bytes, page_num: int) -> List[str]:
        """Extract columns from a single sample page with fresh LLM instance"""
        llm = self.create_llm()
        try:
            return await self._extract_columns_from_page(llm, page_image_bytes, page_num)
        except Exception as e:
            logger.warning(f"Sample page {page_num} column extraction failed: {e}")
            return []

    @retry(
        retry=retry_if_exception(lambda e: not isinstance(e, IntentionalEmptyResultError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True
    )
    async def _extract_columns_from_page(self, llm, page_image_bytes: bytes, page_num: int) -> List[str]:
        """Extract only column names from a page image"""
        try:
            parser = JsonOutputParser(pydantic_object=ColumnSchema)
            format_instructions = parser.get_format_instructions()
            
            prompt_text = f"""You are a bank statement analyzer. Your ONLY task is to identify and extract the column headers from this bank statement page.

## CRITICAL REQUIREMENTS:
- **EXTRACT ONLY COLUMN HEADERS** - ignore all transaction data
- **PRESERVE EXACT TEXT** - keep column names exactly as they appear, no translation or character substitution
- **ORIGINAL LANGUAGE** - maintain all languages and scripts exactly as shown
- **NO DUPLICATES** - list each unique column name only once

## TASK:
Look at this bank statement page image and identify ALL column headers in the table(s). Extract only the header row text.

## OUTPUT FORMAT:
{format_instructions}

Return a JSON object with a "columns" array containing the exact column names as they appear in the image."""

            image_base64 = base64.b64encode(page_image_bytes).decode('utf-8')
            
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}
                ]
            )
            
            async with asyncio.timeout(90):
                response = await llm.ainvoke([message])
            
            if not response or not response.content:
                logger.warning(f"Page {page_num}: Empty response for column extraction")
                return []
            
            try:
                result = parser.parse(response.content)
                # Handle both Pydantic model and dictionary responses
                if hasattr(result, 'columns'):
                    return result.columns
                elif isinstance(result, dict) and 'columns' in result:
                    return result['columns']
                else:
                    logger.warning(f"Page {page_num}: Unexpected result format: {result}")
                    return []
            except Exception as e:
                logger.error(f"Page {page_num}: Failed to parse column extraction response: {e}")
                # Fallback to manual JSON extraction
                import re
                json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
                if json_match:
                    try:
                        result_dict = json.loads(json_match.group())
                        return result_dict.get('columns', [])
                    except json.JSONDecodeError:
                        pass
                return []
                
        except asyncio.TimeoutError:
            logger.error(f"Page {page_num}: Column extraction timed out after 90 seconds")
            raise RetryableAPIError(f"Timeout error for column extraction on page {page_num}") from None
        except Exception as e:
            if is_retryable_error(e):
                raise RetryableAPIError(f"API error for column extraction on page {page_num}: {e}") from e
            else:
                logger.error(f"Page {page_num}: Non-retryable error in column extraction: {type(e).__name__}: {e}")
                return []

    async def standardize_column_names(self, extracted_columns: List[str]) -> List[str]:
        """Phase 2: Use LLM to standardize and finalize column names"""
        if not extracted_columns:
            return []
            
        logger.info(f"Phase 2: Standardizing {len(extracted_columns)} extracted column names")
        
        llm = self.create_llm()
        parser = JsonOutputParser(pydantic_object=StandardizedColumns)
        format_instructions = parser.get_format_instructions()
        
        prompt_text = f"""You are a bank statement column standardization expert. Your task is to analyze these extracted column names and provide a final standardized list.

## EXTRACTED COLUMNS FROM SAMPLE PAGES:
{extracted_columns}

## YOUR TASK:
1. **REMOVE DUPLICATES**: Identify columns that are the same but have slight variations
2. **PRESERVE ORIGINAL LANGUAGE**: Keep the most accurate/complete version of each column name
3. **NO TRANSLATION**: Never translate - keep original language and script
4. **CONSOLIDATE VARIATIONS**: If you see "التاريخ", "Date", "التاريخ_ميلادي" - choose the most common/complete version
5. **MAINTAIN INTEGRITY**: Preserve exact Unicode characters and scripts

## RULES:
- Choose the BEST version of each column (most complete, most accurate)
- Remove obvious duplicates and variations
- Keep all languages as they originally appear
- Prioritize clarity and consistency
- If unsure between variations, pick the more descriptive one

## OUTPUT FORMAT:
{format_instructions}

Provide the final standardized column list that will be used for consistent extraction across all pages."""

        try:
            async with asyncio.timeout(90):
                response = await llm.ainvoke([HumanMessage(content=prompt_text)])
            
            if not response or not response.content:
                logger.warning("Empty response for column standardization, using original columns")
                return extracted_columns
            
            try:
                result = parser.parse(response.content)
                # Handle both Pydantic model and dictionary responses
                if hasattr(result, 'final_columns'):
                    final_columns = result.final_columns
                elif isinstance(result, dict) and 'final_columns' in result:
                    final_columns = result['final_columns']
                else:
                    logger.warning(f"Unexpected standardization result format: {result}")
                    final_columns = extracted_columns
                    
                logger.info(f"Phase 2 complete: Standardized to {len(final_columns)} columns: {final_columns}")
                return final_columns
            except Exception as e:
                logger.error(f"Failed to parse column standardization response: {e}")
                # Fallback to manual JSON extraction
                import re
                json_match = re.search(r'\{.*\}', response.content, re.DOTALL)
                if json_match:
                    try:
                        result_dict = json.loads(json_match.group())
                        return result_dict.get('final_columns', extracted_columns)
                    except json.JSONDecodeError:
                        pass
                return extracted_columns
                
        except Exception as e:
            logger.error(f"Error in column standardization: {e}")
            return extracted_columns
    
    async def combine_tables(self, all_tables: List[Dict]) -> Optional[pd.DataFrame]:
        """Combine tables from all pages into one DataFrame."""
        logger.info(f"Combining {len(all_tables)} tables")
        
        if not all_tables:
            return None
        
        dataframes = []
        for table_info in all_tables:
            df = table_info['dataframe']
            if df is not None and not df.empty:
                # Add page number column for reference
                df['Source_Page'] = table_info['page_number']
                dataframes.append(df)
        
        if not dataframes:
            return None
        
        try:
            # Combine all dataframes
            combined_df = pd.concat(dataframes, ignore_index=True, sort=False)
            combined_df = combined_df.dropna(how='all')  # Remove completely empty rows
            
            logger.info(f"Successfully combined tables: {len(combined_df)} total rows")
            return combined_df
            
        except Exception as e:
            logger.error(f"Error combining tables: {e}")
            return dataframes[0] if dataframes else None
    
    async def create_excel_file(self, df: pd.DataFrame, filename: str) -> str:
        """Create Excel file with professional formatting."""
        logger.info(f"Creating Excel file for {filename}")
        
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_name = filename.replace('.pdf', '').replace(' ', '_')
        excel_filename = f"{base_name}_extracted_{current_time}.xlsx"
        
        # Create temp file
        temp_dir = tempfile.gettempdir()
        excel_path = os.path.join(temp_dir, excel_filename)
        
        try:
            # Create Excel with formatting
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Bank Statement', index=False)
                
                # Get the workbook and worksheet
                workbook = writer.book
                worksheet = writer.sheets['Bank Statement']
                
                # Auto-adjust column widths
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
            
            logger.info(f"Excel file created successfully: {excel_path}")
            return excel_path
            
        except Exception as e:
            logger.error(f"Error creating Excel file: {e}")
            raise


# Global instance
pdf_extraction_service = UniversalPDFExtractionService()
