import os
import time
import sys
from openai import OpenAI
from openai.types.chat import ChatCompletion

def process_file(input_file: str) -> None:
    # Read static content from prompt.txt in the root directory
    with open("prompt.txt", 'r', encoding='utf-8', errors='ignore') as file:
        static_content = file.read()

    # Read the input file content
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as file:
        file_content = file.read()

    # Create the full prompt
    full_prompt = static_content + "\n" + file_content

    # Initialize the OpenAI client with GitHub token
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=os.environ["GITHUB_TOKEN"],
    )

    # Retry mechanism with exponential backoff
    max_retries = 5
    retry_delay = 1  # Initial delay in seconds

    for attempt in range(max_retries):
        try:
            response: ChatCompletion = client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "",
                    },
                    {
                        "role": "user",
                        "content": full_prompt,
                    }
                ],
                model="gpt-4o",
                temperature=1,
                max_tokens=4096,
                top_p=1
            )
            
            # Write the response to a summary file
            output_file_path = f"{input_file}_summary"
            with open(output_file_path, "w", encoding='utf-8') as output_file:
                output_file.write(response.choices[0].message.content)
            
            # Add a delay between requests
            time.sleep(2)  # Delay for 2 seconds
            break  # Exit the retry loop if the request is successful
            
        except Exception as e:
            if hasattr(e, 'status_code') and e.status_code == 429:
                retry_delay = int(getattr(e, 'headers', {}).get("Retry-After", retry_delay))
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"Failed to process {input_file} after {max_retries} attempts")
                raise

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python strip2ship.py <input_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' does not exist")
        sys.exit(1)
    
    process_file(input_file)
    print(f"Successfully processed {input_file}")