import os
import zipfile
import shutil
from pathlib import Path
import math
from typing import List, Dict
import json
import subprocess
import logging
import time
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('process_repository.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_processed_files():
    """Load the list of processed files from a JSON file."""
    processed_files_path = os.path.join(os.path.dirname(__file__), 'processed_files.json')
    try:
        with open(processed_files_path, 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_processed_files(processed_files):
    """Save the list of processed files to a JSON file."""
    processed_files_path = os.path.join(os.path.dirname(__file__), 'processed_files.json')
    with open(processed_files_path, 'w') as f:
        json.dump(list(processed_files), f)

def count_tokens(text: str) -> int:
    # Simple approximation: 1 token ≈ 4 characters
    return len(text) // 4

def chunk_file_content(content: str, max_tokens: int) -> List[str]:
    chunks = []
    current_chunk = ""
    current_token_count = 0
    
    # Split by lines to maintain code structure
    lines = content.split('\n')
    
    for line in lines:
        line_tokens = count_tokens(line + '\n')
        if current_token_count + line_tokens > max_tokens:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line + '\n'
            current_token_count = line_tokens
        else:
            current_chunk += line + '\n'
            current_token_count += line_tokens
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks

def process_file(src_path: str, dest_path: str, max_tokens: int, processed_files: set) -> List[str]:
    logger.info(f"Processing file: {src_path}")
    try:
        with open(src_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        chunks = chunk_file_content(content, max_tokens)
        chunk_files = []
        
        for i, chunk in enumerate(chunks, 1):
            chunk_file = f"{dest_path}_{i:03d}"
            # Use absolute path for consistency in processed files check
            abs_chunk_file = os.path.abspath(chunk_file)
            if abs_chunk_file in processed_files:
                logger.info(f"Skipping already processed chunk: {chunk_file}")
                chunk_files.append(chunk_file)
                continue
                
            with open(chunk_file, 'w', encoding='utf-8') as f:
                f.write(chunk)
            chunk_files.append(chunk_file)
            logger.info(f"Created chunk {i}/{len(chunks)}: {chunk_file}")
        
        return chunk_files
    except Exception as e:
        logger.error(f"Error processing file {src_path}: {str(e)}")
        raise

def batch_summaries(summary_files: List[str], batch_size: int = 15) -> List[List[str]]:
    return [summary_files[i:i + batch_size] for i in range(0, len(summary_files), batch_size)]

def run_strip2ship(input_file: str, max_retries: int = 3) -> bool:
    retry_delay = 1
    # Use absolute path for consistency in processed files check
    abs_input_file = os.path.abspath(input_file)
    for attempt in range(max_retries):
        try:
            logger.info(f"Running strip2ship on {input_file} (attempt {attempt + 1}/{max_retries})")
            result = subprocess.run(['python3', 'strip2ship.py', input_file], 
                                  capture_output=True, 
                                  text=True)
            
            if result.returncode != 0:
                logger.error(f"Error processing {input_file}:")
                logger.error(result.stderr)
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                return False
            return True
        except Exception as e:
            logger.error(f"Exception while processing {input_file}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            return False
    return False

def should_process_file(file_path: str) -> bool:
    """Check if a file should be processed."""
    # Skip .git and .terraform directories and their contents
    if any(part in ['/.git/', '/.terraform/'] for part in file_path.split(os.sep)) or \
       any(file_path.startswith(prefix) for prefix in ['.git/', '.terraform/']):
        return False
    # Skip summary files and response files
    if file_path.endswith(('_summary', '_response.txt')):
        return False
    return True

def main():
    # Constants
    PROMPT_SIZE = 38  # Size of prompt.txt
    MAX_TOKENS = 4096 - PROMPT_SIZE
    SRC_DIR = "src"
    DEST_DIR = "dest"
    
    logger.info("Starting repository processing")
    
    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("Error: OPENAI_API_KEY environment variable must be set")
        return
    
    # Create dest directory if it doesn't exist
    os.makedirs(DEST_DIR, exist_ok=True)
    
    # Load processed files and convert to absolute paths
    processed_files = {os.path.abspath(f) for f in load_processed_files()}
    logger.info(f"Loaded {len(processed_files)} previously processed files")
    
    # Look for zip files in src directory
    zip_files = [f for f in os.listdir(SRC_DIR) if f.endswith('.zip')]
    
    if not zip_files:
        logger.warning("No zip files found in src directory")
        return
    
    logger.info(f"Found {len(zip_files)} zip files to process")
    
    for zip_file in zip_files:
        zip_path = os.path.join(SRC_DIR, zip_file)
        extract_dir = os.path.join(SRC_DIR, os.path.splitext(zip_file)[0])
        
        logger.info(f"Processing zip file: {zip_file}")
        
        # Extract zip file
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            logger.info(f"Extracted {zip_file} to {extract_dir}")
        except Exception as e:
            logger.error(f"Failed to extract {zip_file}: {str(e)}")
            continue
        
        # Process each file in the extracted directory
        for root, dirs, files in os.walk(extract_dir):
            # Skip .git and .terraform directories
            dirs[:] = [d for d in dirs if d not in ['.git', '.terraform']]
            
            # Create corresponding directory structure in dest
            rel_path = os.path.relpath(root, extract_dir)
            dest_root = os.path.join(DEST_DIR, rel_path)
            os.makedirs(dest_root, exist_ok=True)
            
            # Process regular files
            summary_files = []
            for file in files:
                src_file = os.path.join(root, file)
                
                # Skip files that shouldn't be processed
                if not should_process_file(src_file):
                    logger.debug(f"Skipping file: {src_file}")
                    continue
                
                dest_file = os.path.join(dest_root, file)
                
                try:
                    # Process file into chunks
                    chunk_files = process_file(src_file, dest_file, MAX_TOKENS, processed_files)
                    
                    # Process each chunk with strip2ship
                    for chunk_file in chunk_files:
                        abs_chunk_file = os.path.abspath(chunk_file)
                        if abs_chunk_file in processed_files:
                            logger.info(f"Skipping already processed chunk: {chunk_file}")
                            summary_file = f"{chunk_file}_summary"
                            if os.path.exists(summary_file):
                                summary_files.append(summary_file)
                            continue
                            
                        if run_strip2ship(chunk_file):
                            summary_file = f"{chunk_file}_summary"
                            if os.path.exists(summary_file):
                                summary_files.append(summary_file)
                                logger.info(f"Added summary file: {summary_file}")
                except Exception as e:
                    logger.error(f"Failed to process file {src_file}: {str(e)}")
                    continue
            
            # Process summaries in batches of 15
            if summary_files:
                batches = batch_summaries(summary_files)
                logger.info(f"Processing {len(batches)} batches of summaries")
                
                for i, batch in enumerate(batches):
                    # Create a combined input file for the batch
                    batch_input = os.path.join(dest_root, f"batch_{i+1:03d}.txt")
                    abs_batch_input = os.path.abspath(batch_input)
                    if abs_batch_input in processed_files:
                        logger.info(f"Skipping already processed batch: {batch_input}")
                        continue
                        
                    try:
                        with open(batch_input, 'w', encoding='utf-8') as f:
                            for summary_file in batch:
                                with open(summary_file, 'r', encoding='utf-8') as sf:
                                    f.write(sf.read() + '\n---\n')
                        
                        # Process the batch with strip2ship
                        if run_strip2ship(batch_input):
                            logger.info(f"Successfully processed batch {i+1}")
                        else:
                            logger.error(f"Failed to process batch {i+1}")
                    except Exception as e:
                        logger.error(f"Error processing batch {i+1}: {str(e)}")
        
        # Clean up extracted directory
        try:
            shutil.rmtree(extract_dir)
            logger.info(f"Cleaned up extracted directory: {extract_dir}")
        except Exception as e:
            logger.error(f"Failed to clean up {extract_dir}: {str(e)}")
    
    # Final processing of all directory summaries
    all_summaries = []
    logger.info("Processing final directory summaries")
    
    for root, dirs, files in os.walk(DEST_DIR):
        summary_files = [f for f in files if f.endswith('_summary')]
        if summary_files:
            batches = batch_summaries(summary_files)
            # Get relative path from DEST_DIR and convert slashes to dashes
            rel_path = os.path.relpath(root, DEST_DIR).replace(os.sep, '-')
            if rel_path == '.':
                rel_path = 'root'
                
            for i, batch in enumerate(batches):
                # Include path in the batch filename
                batch_input = os.path.join(DEST_DIR, f"directory_summary-{rel_path}-batch_{i+1:03d}.txt")
                abs_batch_input = os.path.abspath(batch_input)
                if abs_batch_input in processed_files:
                    logger.info(f"Skipping already processed directory summary: {batch_input}")
                    all_summaries.append(batch_input)
                    continue
                    
                try:
                    with open(batch_input, 'w', encoding='utf-8') as f:
                        # Write the directory path as a header
                        f.write(f"Directory: {os.path.relpath(root, DEST_DIR)}\n")
                        f.write("=" * 80 + "\n\n")
                        for summary_file in batch:
                            # Include the relative path of the summary file
                            rel_summary_path = os.path.relpath(summary_file, DEST_DIR)
                            f.write(f"File: {rel_summary_path}\n")
                            f.write("-" * 80 + "\n")
                            with open(os.path.join(root, summary_file), 'r', encoding='utf-8') as sf:
                                f.write(sf.read())
                            f.write("\n\n")
                    all_summaries.append(batch_input)
                    logger.info(f"Created directory summary batch {i+1} for {rel_path}")
                except Exception as e:
                    logger.error(f"Error creating directory summary batch {i+1} for {rel_path}: {str(e)}")
    
    # Create final summary
    if all_summaries:
        final_input = os.path.join(os.path.dirname(DEST_DIR), "final_summary.txt")
        abs_final_input = os.path.abspath(final_input)
        if abs_final_input in processed_files:
            logger.info("Final summary already processed")
        else:
            try:
                with open(final_input, 'w', encoding='utf-8') as f:
                    for summary_file in all_summaries:
                        # Get the directory path from the summary filename
                        summary_name = os.path.basename(summary_file)
                        f.write(f"Summary from: {summary_name}\n")
                        f.write("=" * 80 + "\n\n")
                        with open(summary_file, 'r', encoding='utf-8') as sf:
                            f.write(sf.read())
                        f.write("\n" + "=" * 80 + "\n\n")
                if run_strip2ship(final_input):
                    logger.info("Successfully created final summary")
                else:
                    logger.error("Failed to create final summary")
            except Exception as e:
                logger.error(f"Error creating final summary: {str(e)}")
    
    logger.info("Repository processing completed")

if __name__ == "__main__":
    main() 