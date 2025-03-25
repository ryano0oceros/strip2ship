import os
import time
import sys
import logging
import json
from datetime import datetime
from openai import OpenAI

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('strip2ship.log'),
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

def process_file(input_file: str, processed_files: set) -> None:
    # Convert to absolute path for consistency
    abs_input_file = os.path.abspath(input_file)
    
    # Skip if already processed
    if abs_input_file in processed_files:
        logger.info(f"Skipping already processed file: {input_file}")
        return

    logger.info(f"Processing file: {input_file}")
    
    # Read static content from prompt.txt in the root directory
    try:
        with open("prompt.txt", 'r', encoding='utf-8', errors='ignore') as file:
            static_content = file.read()
    except Exception as e:
        logger.error(f"Failed to read prompt.txt: {str(e)}")
        raise

    # Read the input file content
    try:
        with open(input_file, 'r', encoding='utf-8', errors='ignore') as file:
            file_content = file.read()
    except Exception as e:
        logger.error(f"Failed to read input file {input_file}: {str(e)}")
        raise

    # Create the full prompt
    full_prompt = static_content + "\n" + file_content

    # Initialize the OpenAI client
    client = OpenAI()

    # Retry mechanism with exponential backoff
    max_retries = 5
    retry_delay = 1  # Initial delay in seconds
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries} for {input_file}")
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ],
                temperature=1,
                max_tokens=2048,
                top_p=1
            )
            
            # Write the response to a summary file
            output_file_path = f"{input_file}_summary"
            with open(output_file_path, "w", encoding='utf-8') as output_file:
                output_file.write(response.choices[0].message.content)
            
            # Mark file as processed using absolute path
            processed_files.add(abs_input_file)
            save_processed_files(processed_files)
            
            logger.info(f"Successfully processed {input_file} -> {output_file_path}")
            
            # Add a delay between requests
            time.sleep(2)  # Delay for 2 seconds
            break  # Exit the retry loop if the request is successful
            
        except Exception as e:
            last_error = e
            if hasattr(e, 'status_code') and e.status_code == 429:
                retry_after = int(getattr(e, 'headers', {}).get("Retry-After", retry_delay))
                logger.warning(f"Rate limit hit for {input_file}. Waiting {retry_after} seconds before retry.")
                time.sleep(retry_after)
                retry_delay = retry_after * 2  # Exponential backoff
            else:
                logger.error(f"Error processing {input_file}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise

    if last_error:
        logger.error(f"Failed to process {input_file} after {max_retries} attempts. Last error: {str(last_error)}")
        raise last_error

if __name__ == "__main__":
    if len(sys.argv) != 2:
        logger.error("Usage: python strip2ship.py <input_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        logger.error(f"Error: Input file '{input_file}' does not exist")
        sys.exit(1)
    
    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("Error: OPENAI_API_KEY environment variable must be set")
        sys.exit(1)
    
    try:
        processed_files = load_processed_files()
        process_file(input_file, processed_files)
        logger.info(f"Successfully completed processing {input_file}")
    except Exception as e:
        logger.error(f"Failed to process {input_file}: {str(e)}")
        sys.exit(1)