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
            max_retries=2,
            request_timeout=60
        )

    async def extract_bank_statement(self, file_bytes: bytes, filename: str, required_columns: Optional[List[str]] = None, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Extract bank statement data using simple async batching"""
        logger.info(f"Starting universal table extraction for {filename}")

        try:
            start_time = time.time()
            
            # Get all pages from PDF
            pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
            total_pages = len(pdf_document)
            pdf_document.close()
            
            logger.info(f"Processing {total_pages} pages")
            
            # Extract tables from each page using async batching
            all_tables = await self.extract_bank_statement_async_batching(
                file_bytes, total_pages, required_columns, task_id
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
        
        # Create async tasks for each batch
        batch_tasks = []
        for i, page_numbers in enumerate(page_batches):
            task = self.process_page_batch_simple(
                file_bytes, page_numbers, required_columns, task_id, 
                completed_pages_lock, completed_pages_count, total_pages
            )
            batch_tasks.append(task)
        
        # Execute all batches concurrently with asyncio.gather
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
                    # Extract text from this specific page
                    pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
                    page = pdf_document.load_page(page_num - 1)  # fitz uses 0-based indexing
                    page_text = page.get_text()
                    pdf_document.close()
                    
                    if not page_text.strip():
                        logger.warning(f"Page {page_num} appears to be empty, skipping")
                        continue
                    
                    # Use the LLM to extract table data from this page
                    try:
                        result = await self.extract_table_from_page_text(llm, page_text, page_num, required_columns)
                    except RetryableAPIError as e:
                        logger.error(f"Page {page_num}: API error persisted after retries: {e}")
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

    async def extract_table_from_page_text(self, llm, page_text: str, page_num: int, 
                                          required_columns: Optional[List[str]]) -> Optional[Dict]:
        """Extract table data from page text using LLM with LangChain JSON parser"""
        return await self._extract_with_retry(llm, page_text, page_num, required_columns)
    
    @retry(
        retry=retry_if_exception(lambda e: is_retryable_error(e)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
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
            
            prompt = f"""
            Extract bank statement transaction data from the following text. {columns_instruction}
            
            {format_instructions}
            
            If no transaction data is found, return {{"table_data": []}}
            
            Text to analyze:
            {page_text}
            """
            
            # Make async call to LLM
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
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
                logger.error(f"Page {page_num}: Non-retryable error in LLM extraction: {e}")
                return None
    
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
