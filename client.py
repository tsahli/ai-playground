import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import boto3
from boto3.session import Session
from botocore.client import BaseClient

from system_prompt import SYSTEM_PROMPT
from tool import Tool
import yaml

@dataclass
class ModelResponse:
    content: str
    stop_reason: str
    usage: dict
    metrics: dict
    tool_calls: Optional[List[Dict]] = None


class BedrockClient:
    DEFAULT_MODEL_ARN = "arn:aws:bedrock:us-east-1:518030533805:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0"

    def __init__(
        self,
        profile_name: str = "np-farmers",
        region_name: str = "us-east-1",
        system_prompt: Optional[str] = None,
        model_arn: Optional[str] = None,
        doc_dirs: Optional[List[str]] = None,
    ):
        self.session: Session = boto3.Session(profile_name=profile_name)
        self.client: BaseClient = self.session.client(
            "bedrock-runtime",
            region_name=region_name,
        )
        self.conversation_history = []
        self.model_arn = model_arn or self.DEFAULT_MODEL_ARN
        self.tools = {}

        # Load reference documentation
        doc_dirs = doc_dirs or ["dispute_docs", "scanline_docs"]
        docs = [self._load_docs(dir) for dir in doc_dirs if os.path.exists(dir)]
        reference_docs = "\n\n".join(docs)

        # Set system prompt
        default_prompt = SYSTEM_PROMPT
        self.system_prompt = f"{system_prompt or default_prompt}\n\nReference Documentation:\n{reference_docs}"

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def _load_system_prompt(self, system_prompt_path: Optional[str]) -> Optional[str]:
        """Load and parse the system prompt from a YAML file."""
        if system_prompt_path:
            with open(system_prompt_path, "r") as file:
                content = yaml.safe_load(file)
            return yaml.dump(content)  # Convert back to a string if needed
        return None

    def invoke_model(
        self, prompt: str, include_history: bool = True, max_tool_rounds: int = 5
    ) -> ModelResponse:
        messages = self.conversation_history.copy() if include_history else []
        messages.append({"role": "user", "content": [{"text": prompt}]})

        request = self._build_request(messages)

        for _ in range(max_tool_rounds):
            response = self._parse_response(self.client.converse(**request))

            if not response.tool_calls:
                if include_history:
                    self._update_history(messages, response)
                return response

            # Handle tool calls
            messages.extend(self._process_tool_calls(response))
            request["messages"] = messages

        raise Exception(f"Exceeded maximum tool rounds ({max_tool_rounds})")

    def _build_request(self, messages: List[Dict]) -> Dict:
        request = {
            "modelId": self.model_arn,
            "system": [{"text": self._load_system_prompt("system_prompt.yml")}],
            "messages": messages,
        }

        if self.tools:
            request["toolConfig"] = {
                "tools": [tool.to_dict() for tool in self.tools.values()],
                "toolChoice": {"auto": {}},
            }

        return request

    def _process_tool_calls(self, response: ModelResponse) -> List[Dict]:
        messages = []

        # Add assistant message with tool calls
        assistant_content = [{"text": response.content}] if response.content else []
        assistant_content.extend(
            [
                {
                    "toolUse": {
                        "toolUseId": call["id"],
                        "name": call["name"],
                        "input": call["parameters"],
                    }
                }
                for call in response.tool_calls
            ]
        )
        messages.append({"role": "assistant", "content": assistant_content})

        # Execute tools and add results
        results = []
        for tool_call in response.tool_calls:
            result = self._execute_tool(tool_call)
            results.append(
                {
                    "toolUseId": tool_call["id"],
                    "content": [{"text": self._format_result(result)}],
                    "status": "success" if "error" not in result else "error",
                }
            )

        messages.append(
            {"role": "user", "content": [{"toolResult": r} for r in results]}
        )
        return messages

    def _execute_tool(self, tool_call: Dict) -> Dict:
        try:
            tool = self.tools[tool_call["name"]]
            return tool.function(**tool_call["parameters"])
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _format_result(result: any) -> str:
        if isinstance(result, (dict, list)):
            return json.dumps(result)
        return str(result)

    def _update_history(self, messages: List[Dict], response: ModelResponse) -> None:
        self.conversation_history = messages
        self.conversation_history.append(
            {"role": "assistant", "content": [{"text": response.content}]}
        )

    @staticmethod
    def _load_docs(docs_dir: str) -> str:
        docs = []
        for filename in os.listdir(docs_dir):
            with open(f"{docs_dir}/{filename}", "r") as f:
                docs.append(f.read())
        return "\n\n".join(docs)

    @staticmethod
    def _parse_response(response: dict) -> ModelResponse:
        content = ""
        tool_calls = []

        for item in response["output"]["message"]["content"]:
            if "text" in item:
                content += item["text"]
            elif "toolUse" in item:
                tool_use = item["toolUse"]
                tool_calls.append(
                    {
                        "id": tool_use["toolUseId"],
                        "name": tool_use["name"],
                        "parameters": tool_use["input"],
                    }
                )

        return ModelResponse(
            content=content.strip(),
            stop_reason=response["stopReason"],
            usage=response["usage"],
            metrics=response.get("metrics", {}),
            tool_calls=tool_calls,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Interact with Bedrock Claude model",
    )
    parser.add_argument(
        "--profile",
        default="np-farmers",
        help="AWS profile name",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region name",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Disable conversation history",
    )
    parser.add_argument(
        "--prompt",
        help="Single prompt to send",
    )
    parser.add_argument(
        "--system-prompt",
        help="Override default system prompt",
    )
    parser.add_argument(
        "--model-arn",
        help="Override default model ARN",
    )
    parser.add_argument(
        "--doc-dirs",
        nargs="*",
        default=["dispute_docs", "scanline_docs"],
    )

    args = parser.parse_args()

    try:
        client = BedrockClient(
            profile_name=args.profile,
            region_name=args.region,
            model_arn=args.model_arn,
            system_prompt=args.system_prompt,
            doc_dirs=args.doc_dirs,
        )

        # Register tools
        from s3_tools import S3FileAnalyzer

        client.register_tool(S3FileAnalyzer(client.session).create_tool())

        try:
            from config import CHECKOUT_API_KEY
            from dispute_analyzer import DisputeAnalyzer

            client.register_tool(DisputeAnalyzer(CHECKOUT_API_KEY).create_tool())
        except ImportError:
            print("Warning: config.py not found. Checkout.com API features disabled.")

        if args.prompt:
            response = client.invoke_model(args.prompt, not args.no_history)
            print(response.content)
        else:
            run_interactive_mode(client, not args.no_history)

    except Exception as e:
        print(f"Error: {str(e)}")
        exit(1)


def run_interactive_mode(client: BedrockClient, include_history: bool):
    print("Enter your prompts (Ctrl+D or Ctrl+C to exit):")
    try:
        while True:
            try:
                prompt = input("\nPrompt> ").strip()
                if prompt:
                    response = client.invoke_model(prompt, include_history)
                    print("\nResponse:", response.content)
            except (KeyboardInterrupt, EOFError):
                break
            except Exception as e:
                print(f"\nError: {str(e)}")
    except KeyboardInterrupt:
        pass
    print("\nExiting...")


if __name__ == "__main__":
    main()
