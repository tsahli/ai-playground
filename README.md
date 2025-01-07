### Bedrock Claude Client

A Python client for interacting with Amazon Bedrock's Claude models, with built-in support for S3 file analysis and conversation history.

### Installation

1. Clone this repository
2. Create and activate a virtual environment:
   ```
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
5. Create a `config.py` file with `CHECKOUT_API_KEY`

### Usage

#### Basic Usage

```
from client import BedrockClient

client = BedrockClient()
response = client.invoke_model("Your prompt here")
print(response.content)
```

#### Command Line Interface

```
# interactive mode
python client.py

# single prompt
python client.py --prompt "teach me to play chess"

# single prompt with system prompt override
python client.py --prompt "teach me to play chess" --system-prompt "talk like a pirate"
```

### Configuration Options

- `--profile`: AWS profile name (default: "np-farmers")
- `--region`: AWS region (default: "us-east-1")
- `--no-history`: Disable conversation history
- `--system-prompt`: Override default system prompt
- `--model-arn`: Override default Claude model ARN
- `--doc-dirs`: Specify documentation directories

### Reference Documentation

The client loads reference documentation from:

- [`dispute_docs/`](dispute_docs/): Documentation about dispute handling
- [`scanline_docs/`](scanline_docs/): Documentation about scanline functionality
