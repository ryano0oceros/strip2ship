import os
import zipfile
import shutil
from pathlib import Path
import math
from typing import List, Dict
import json

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

def process_file(src_path: str, dest_path: str, max_tokens: int) -> List[str]:
    with open(src_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    chunks = chunk_file_content(content, max_tokens)
    chunk_files = []
    
    for i, chunk in enumerate(chunks, 1):
        chunk_file = f"{dest_path}_{i:03d}"
        with open(chunk_file, 'w', encoding='utf-8') as f:
            f.write(chunk)
        chunk_files.append(chunk_file)
    
    return chunk_files

def batch_summaries(summary_files: List[str], batch_size: int = 15) -> List[List[str]]:
    return [summary_files[i:i + batch_size] for i in range(0, len(summary_files), batch_size)]

def main():
    # Constants
    PROMPT_SIZE = 38  # Size of prompt.txt
    MAX_TOKENS = 4096 - PROMPT_SIZE
    SRC_DIR = "src"
    DEST_DIR = "dest"
    
    # Create dest directory if it doesn't exist
    os.makedirs(DEST_DIR, exist_ok=True)
    
    # Look for zip files in src directory
    zip_files = [f for f in os.listdir(SRC_DIR) if f.endswith('.zip')]
    
    for zip_file in zip_files:
        zip_path = os.path.join(SRC_DIR, zip_file)
        extract_dir = os.path.join(SRC_DIR, os.path.splitext(zip_file)[0])
        
        # Extract zip file
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # Process each file in the extracted directory
        for root, dirs, files in os.walk(extract_dir):
            # Create corresponding directory structure in dest
            rel_path = os.path.relpath(root, extract_dir)
            dest_root = os.path.join(DEST_DIR, rel_path)
            os.makedirs(dest_root, exist_ok=True)
            
            # Process regular files
            summary_files = []
            for file in files:
                if file.endswith(('_summary', '_response.txt')):
                    continue
                    
                src_file = os.path.join(root, file)
                dest_file = os.path.join(dest_root, file)
                
                # Process file into chunks
                chunk_files = process_file(src_file, dest_file, MAX_TOKENS)
                
                # Process each chunk with strip2ship
                for chunk_file in chunk_files:
                    os.system(f'python strip2ship.py "{chunk_file}"')
                    summary_file = f"{chunk_file}_summary"
                    if os.path.exists(summary_file):
                        summary_files.append(summary_file)
            
            # Process summaries in batches of 15
            if summary_files:
                batches = batch_summaries(summary_files)
                for i, batch in enumerate(batches):
                    # Create a combined input file for the batch
                    batch_input = os.path.join(dest_root, f"batch_{i+1:03d}.txt")
                    with open(batch_input, 'w', encoding='utf-8') as f:
                        for summary_file in batch:
                            with open(summary_file, 'r', encoding='utf-8') as sf:
                                f.write(sf.read() + '\n---\n')
                    
                    # Process the batch with strip2ship
                    os.system(f'python strip2ship.py "{batch_input}"')
        
        # Clean up extracted directory
        shutil.rmtree(extract_dir)
    
    # Final processing of all directory summaries
    all_summaries = []
    for root, dirs, files in os.walk(DEST_DIR):
        summary_files = [f for f in files if f.endswith('_summary')]
        if summary_files:
            batches = batch_summaries(summary_files)
            for i, batch in enumerate(batches):
                batch_input = os.path.join(DEST_DIR, f"directory_summary_{len(all_summaries)+1:03d}.txt")
                with open(batch_input, 'w', encoding='utf-8') as f:
                    for summary_file in batch:
                        with open(os.path.join(root, summary_file), 'r', encoding='utf-8') as sf:
                            f.write(sf.read() + '\n---\n')
                all_summaries.append(batch_input)
    
    # Create final summary
    if all_summaries:
        final_input = os.path.join(os.path.dirname(DEST_DIR), "final_summary.txt")
        with open(final_input, 'w', encoding='utf-8') as f:
            for summary_file in all_summaries:
                with open(summary_file, 'r', encoding='utf-8') as sf:
                    f.write(sf.read() + '\n---\n')
        os.system(f'python strip2ship.py "{final_input}"')

if __name__ == "__main__":
    main() 