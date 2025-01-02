### Bedrock Claude Client

A Python client for interacting with Amazon Bedrock's Claude models, with built-in support for S3 file analysis and conversation history.

### Installation

1. Clone this repository
2. Create and activate a virtual environment:
   ```
    # Create virtual environment
    python -m venv venv
    source venv/bin/activate
   ```
3. Install dependencies
   ```
   pip install -r requirements.txt
   ```
4. Login to AWS non-prod farmers (you need the latest Claude model active on your AWS bedrock account)
   ```
   aws sso login --profile np-farmers
   ```

### Basic Usage

```
    # interactive mode
    python client.py

    # single prompt
    python client.py --prompt "teach me to play chess"

    # single prompt with system prompt override
    python client.py --prompt "teach me to play chess" --system-prompt "talk like a pirate"
```
