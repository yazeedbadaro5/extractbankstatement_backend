import io
import json
import time
import base64
import asyncio
import pandas as pd
import os
import tempfile
import multiprocessing as mp
import warnings
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor

# PDF to image conversion
import fitz  # PyMuPDF
from PIL import Image

# LangChain imports
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

# Retry handling
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.configuration.config import settings
from src.utils.logger import get_logger
from src.services.task_manager import task_manager

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

# Redirect stderr to suppress low-level C++ warnings

logger = get_logger(__name__)


class UniversalPDFExtractionService:
    """Universal bank statement extraction service using LangChain multimodal approach"""
    
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-pro-preview-03-25",
            google_api_key=settings.gemini_api_key,
            temperature=0
        )
        
        # System message with universal table extraction instructions
        self.system_message = SystemMessage(content="""
        You are a universal bank statement extraction expert. Your task is to extract and process bank statement data in any language.

        CORE INSTRUCTIONS:
        1. Find the largest, most important table on the page
        2. Extract data exactly as it appears in the original document
        3. Preserve ALL original text (including mixed alphanumeric values)
        4. Do NOT translate, convert, or modify any text
        5. Keep numbers, letters, symbols, and special characters exactly as shown
        6. Maintain original formatting and spacing where possible

        RESPONSE FORMAT (JSON only):
        {
            "table_metadata": {
                "total_rows": [number],
                "total_columns": [number],
                "extracted_columns": [list of column names found]
            },
            "table_data": {
                "headers": [list of column headers],
                "rows": [
                    {"column1": "value1", "column2": "value2"},
                    {"column1": "value3", "column2": "value4"}
                ]
            }
        }

        CRITICAL RULES:
        - Extract text EXACTLY as it appears in the original document
        - Do NOT perform any language-specific processing
        - Do NOT convert number formats or date formats
        - Do NOT translate any content
        - Preserve mixed alphanumeric codes (e.g., "ABC123", "XY-789")
        - Keep all original spacing and special characters
        - Only return valid JSON, no additional text
        """)
    
    @staticmethod
    def pdf_page_to_base64(pdf_bytes: bytes, page_number: int) -> str:
        """Convert a PDF page to base64-encoded image (following LangChain docs pattern)"""
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = pdf_document.load_page(page_number - 1)  # input is one-indexed
        pix = page.get_pixmap(dpi=300)  # Higher DPI for better table recognition
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        pdf_document.close()
        
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    
    async def extract_bank_statement(self, file_bytes: bytes, filename: str, required_columns: Optional[List[str]] = None, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Extract and combine tables from PDF (universal language support)."""
        logger.info(f"Starting universal table extraction for {filename}")

        try:
            start_time = time.time()
            
            # Get all pages from PDF
            pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
            total_pages = len(pdf_document)
            pdf_document.close()
            
            logger.info(f"Processing {total_pages} pages")
            
            # Extract tables from each page using multiprocessing
            all_tables = await self.extract_bank_statement_multiprocessing(
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
    
    async def extract_bank_statement_multiprocessing(self, file_bytes: bytes, total_pages: int, 
                                           required_columns: Optional[List[str]], task_id: Optional[str] = None) -> List[Dict]:
        """Extract tables using multiprocessing with single model initialization per worker."""
        logger.info(f"Extracting tables from {total_pages} pages using multiprocessing")
        
        # Prepare page data
        page_data_list = []
        for page_num in range(1, total_pages + 1):
            page_data_list.append({
                'file_bytes': file_bytes,
                'page_number': page_num,
                'required_columns': required_columns,
                'task_id': task_id,
                'total_pages': total_pages
            })
        
        # Use multiprocessing for extraction
        available_cores = max(1, mp.cpu_count() - 1)
        num_cores = min(available_cores, len(page_data_list))
        logger.info(f"Using {num_cores} CPU cores for processing")
        
        # Create batches
        batch_size = max(1, len(page_data_list) // num_cores)
        batches = [page_data_list[i:i + batch_size] for i in range(0, len(page_data_list), batch_size)]
        
        all_results = []
        pages_completed = 0
        
        with ProcessPoolExecutor(max_workers=num_cores) as executor:
            futures = [executor.submit(UniversalPDFExtractionService.run_batch_in_process, batch) for batch in batches]
            
            for i, future in enumerate(futures):
                try:
                    batch_result = future.result(timeout=600)  # 10 minute timeout
                    all_results.extend(batch_result)
                    pages_completed += len(batch_result)
                    
                    # Update progress after each batch completes
                    if task_id:
                        logger.info(f"Batch {i+1}/{len(futures)} completed. Pages done: {pages_completed}/{total_pages}")
                        task_manager.update_page_progress(task_id, pages_completed, total_pages)
                        
                except Exception as e:
                    logger.error(f"Batch processing failed: {e}")
        
        return all_results
    
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
        base_name = filename.replace('.pdf', '').replace('.PDF', '')
        # Replace spaces and special characters with underscores for clickable links
        clean_base_name = base_name.replace(' ', '_').replace('(', '').replace(')', '').replace('[', '').replace(']', '')
        excel_filename = f"{clean_base_name}_extracted_{current_time}.xlsx"
        temp_dir = tempfile.gettempdir()
        excel_path = os.path.join(temp_dir, excel_filename)
        
        try:
            with pd.ExcelWriter(excel_path, engine='xlsxwriter') as writer:
                workbook = writer.book
                
                # Create formats
                header_format = workbook.add_format({
                    'bold': True,
                    'align': 'center',
                    'valign': 'vcenter',
                    'bg_color': '#D3D3D3',
                    'border': 1
                })
                
                cell_format = workbook.add_format({
                    'align': 'left',
                    'valign': 'vcenter',
                    'border': 1,
                    'text_wrap': True
                })
                
                # Write to Excel
                worksheet = workbook.add_worksheet('Extracted_Data')
                
                # Write headers
                for col_idx, column in enumerate(df.columns):
                    worksheet.write(0, col_idx, column, header_format)
                
                # Write data
                for row_idx, row in df.iterrows():
                    for col_idx, value in enumerate(row):
                        # Write as string to preserve formatting
                        worksheet.write_string(row_idx + 1, col_idx, str(value) if pd.notna(value) else "", cell_format)
                
                # Auto-adjust column widths
                for col_idx, column in enumerate(df.columns):
                    max_len = max(df[column].astype(str).str.len().max(), len(column))
                    worksheet.set_column(col_idx, col_idx, min(max_len + 2, 50))
            
            logger.info(f"Excel file created: {excel_path}")
            logger.info(f"Excel filename: {excel_filename}")
            
            return excel_path
            
        except Exception as e:
            logger.error(f"Error creating Excel file: {e}")
            raise
    
    @staticmethod
    def run_batch_in_process(batch):
        """Entry point for multiprocessing."""
        try:
            return asyncio.run(UniversalPDFExtractionService.process_batch_worker(batch))
        except Exception as e:
            logger.error(f"Error in batch processing: {e}")
            return []
    
    @staticmethod
    async def process_batch_worker(batch):
        """Worker function that initializes model once per process."""
        try:
            # Initialize model once per worker process
            if not settings.gemini_api_key:
                logger.error("Gemini API key not available in worker process")
                return []
            
            # Single model initialization per worker
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-pro-preview-03-25",
                google_api_key=settings.gemini_api_key,
                temperature=0
            )
            
            # Create system message for this worker
            system_message = SystemMessage(content="""
            You are a universal bank statement extraction expert. Your task is to extract and process bank statement data in any language.

            CORE INSTRUCTIONS:
            1. Find the largest, most important table on the page
            2. Extract data exactly as it appears in the original document
            3. Preserve ALL original text (including mixed alphanumeric values)
            4. Do NOT translate, convert, or modify any text
            5. Keep numbers, letters, symbols, and special characters exactly as shown
            6. Maintain original formatting and spacing where possible

            RESPONSE FORMAT (JSON only):
            {
                "table_metadata": {
                    "total_rows": [number],
                    "total_columns": [number],
                    "extracted_columns": [list of column names found]
                },
                "table_data": {
                    "headers": [list of column headers],
                    "rows": [
                        {"column1": "value1", "column2": "value2"},
                        {"column1": "value3", "column2": "value4"}
                    ]
                }
            }

            CRITICAL RULES:
            - Extract text EXACTLY as it appears in the original document
            - Do NOT perform any language-specific processing
            - Do NOT convert number formats or date formats
            - Do NOT translate any content
            - Preserve mixed alphanumeric codes (e.g., "ABC123", "XY-789")
            - Keep all original spacing and special characters
            - Only return valid JSON, no additional text
            """)
            
            logger.info(f"Worker process initialized model once for {len(batch)} pages")
            
            results = []
            for page_data in batch:
                try:
                    result = await UniversalPDFExtractionService.extract_table_from_page(
                        llm,
                        system_message,
                        page_data['file_bytes'],
                        page_data['page_number'],
                        page_data['required_columns']
                    )
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.error(f"Error processing page {page_data['page_number']}: {e}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error in batch worker: {e}")
            return []
    
    @staticmethod
    async def extract_table_from_page(llm, system_message, file_bytes: bytes, page_number: int, 
                                    required_columns: Optional[List[str]]):
        """Extract table from a single page using LangChain multimodal approach."""
        
        # Convert PDF page to base64 image (following LangChain docs)
        base64_image = UniversalPDFExtractionService.pdf_page_to_base64(file_bytes, page_number)
        
        # Create simple human message with column instruction
        if required_columns:
            columns_text = ", ".join(required_columns)
            human_text = f"Extract ONLY these specific columns: {columns_text}"
        else:
            human_text = "Extract ALL columns from the main table"
        
        # Simple human message with just the image and column instruction
        human_message = HumanMessage(content=[
            {"type": "text", "text": human_text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_image}"},
            },
        ])
        
        try:
            # Use tenacity for professional retry handling with asyncio timeout
            response = await UniversalPDFExtractionService._extract_with_retry(llm, system_message, human_message)
            
            if response and response.content:
                # Parse JSON response
                response_text = response.content.strip()
                if response_text.startswith('```json'):
                    response_text = response_text[7:-3]
                elif response_text.startswith('```'):
                    response_text = response_text[3:-3]
                
                table_data = json.loads(response_text)
                
                # Convert to DataFrame
                if 'table_data' in table_data and table_data['table_data']['rows']:
                    df = pd.DataFrame(table_data['table_data']['rows'])
                    
                    return {
                        'dataframe': df,
                        'page_number': page_number,
                        'metadata': table_data.get('table_metadata', {})
                    }
                    
        except Exception as e:
            logger.error(f"Failed to extract table from page {page_number}: {e}")
        
        return None
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    async def _extract_with_retry(llm, system_message, human_message):
        """Extract with professional retry handling and timeout."""
        try:
            # Use asyncio timeout for cleaner async timeout handling
            async with asyncio.timeout(240):  #4 minute timeout per API call
                return await llm.ainvoke([system_message, human_message])
        except asyncio.TimeoutError:
            logger.error("LLM call timed out after 4 minutes")
            raise
        except Exception as e:
            logger.warning(f"LLM call failed, will retry: {e}")
            raise


# Global instance
pdf_extraction_service = UniversalPDFExtractionService()