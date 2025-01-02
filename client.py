import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import boto3
from boto3.session import Session
from botocore.client import BaseClient

from s3_file_analyzer import S3FileAnalyzer
from tool import Tool


@dataclass
class ModelResponse:
    content: str
    stop_reason: str
    usage: dict
    metrics: dict
    tool_calls: Optional[List[Dict]] = None


class BedrockClient:
    DEFAULT_MODEL_ARN = "arn:aws:bedrock:us-east-1:518030533805:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0"
    DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant with access to tools for analyzing S3 resources.
    When users ask about S3 buckets or files, use the analyze_s3 tool to help them. For bucket listings, use the 'list_buckets' operation.
    For file contents, use 'read_text'. For file information, use 'get_file_info'. For PDF analysis, use the 'analyze_pdf' tool with OCR cababilities.
    """

    def __init__(
        self,
        profile_name: str = "np-farmers",
        region_name: str = "us-east-1",
        system_prompt: Optional[str] = None,
        model_arn: Optional[str] = None,
    ) -> None:
        self.session: Session = boto3.Session(profile_name=profile_name)
        self.client: BaseClient = self.session.client(
            service_name="bedrock-runtime",
            region_name=region_name,
        )
        self.conversation_history: List[Dict] = []
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.model_arn = model_arn or self.DEFAULT_MODEL_ARN
        self.tools: Dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def invoke_model(
        self,
        prompt: str,
        include_history: bool = True,
        handle_tool_calls: bool = True,
    ) -> ModelResponse:
        request_params = {
            "modelId": self.model_arn,
            "system": [{"text": self.system_prompt}],
            "messages": [],
        }

        if include_history:
            request_params["messages"].extend(self.conversation_history)
        if self.tools:
            request_params["toolConfig"] = {
                "tools": [tool.to_dict() for tool in self.tools.values()],
                "toolChoice": {"auto": {}},
            }

        current_message = {
            "role": "user",
            "content": [{"text": prompt}],
        }
        request_params["messages"].append(current_message)

        try:
            parsed_response = self._parse_response(
                self.client.converse(**request_params)
            )

            if handle_tool_calls and parsed_response.tool_calls:
                tool_results = self._handle_tool_calls(parsed_response.tool_calls)
                return self._continue_with_tool_results(
                    current_message, parsed_response, tool_results, include_history
                )

            if include_history:
                self.conversation_history.append(current_message)
                self.conversation_history.append(
                    {
                        "role": "assistant",
                        "content": [{"text": parsed_response.content}],
                    }
                )

            return parsed_response

        except Exception as e:
            raise Exception(f"Failed to invoke model: {str(e)}") from e

    def _handle_tool_calls(self, tool_calls: List[Dict]) -> List[Dict]:
        """Execute tool calls and return their results."""
        results = []
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            if tool_name not in self.tools:
                raise ValueError(f"Unknown tool: {tool_name}")

            tool = self.tools[tool_name]
            try:
                parameters = tool_call["parameters"]
                result = tool.function(**parameters)

                results.append(
                    {
                        "toolUseId": tool_call["id"],
                        "content": [
                            {
                                "text": (
                                    json.dumps(result)
                                    if isinstance(result, (dict, list))
                                    else str(result)
                                )
                            }
                        ],
                        "status": "success",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "toolUseId": tool_call["id"],
                        "content": [{"text": str(e)}],
                        "status": "error",
                    }
                )
                print(f"Tool error: {str(e)}")  # Debug output

        return results

    def _continue_with_tool_results(
        self,
        user_message: Dict,
        initial_response: ModelResponse,
        tool_results: List[Dict],
        include_history: bool,
    ) -> ModelResponse:
        messages = self.conversation_history.copy() if include_history else []
        messages.append(user_message)

        # Get the assistant's message content
        assistant_content = [{"text": initial_response.content}]

        # Add toolUse blocks from the initial response
        for tool_call in initial_response.tool_calls:
            assistant_content.append(
                {
                    "toolUse": {
                        "toolUseId": tool_call["id"],
                        "name": tool_call["name"],
                        "input": tool_call["parameters"],
                    }
                }
            )

        # Add the assistant's complete message
        messages.append({"role": "assistant", "content": assistant_content})

        # Add tool results
        messages.append(
            {
                "role": "user",
                "content": [{"toolResult": result} for result in tool_results],
            }
        )

        request_params = {
            "modelId": self.model_arn,
            "system": [{"text": self.system_prompt}],
            "messages": messages,
        }

        if self.tools:
            request_params["toolConfig"] = {
                "tools": [tool.to_dict() for tool in self.tools.values()],
                "toolChoice": {"auto": {}},
            }

        try:
            response = self.client.converse(**request_params)
            final_response = self._parse_response(response)

            if include_history:
                self.conversation_history = messages
                self.conversation_history.append(
                    {
                        "role": "assistant",
                        "content": [{"text": final_response.content}],
                    }
                )

            return final_response
        except Exception as e:
            raise

    @staticmethod
    def _parse_response(response: dict) -> ModelResponse:
        content = ""
        tool_calls = []

        message_content = response["output"]["message"]["content"]

        for item in message_content:
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


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interact with Bedrock Claude model")
    parser.add_argument(
        "--profile",
        type=str,
        default="np-farmers",
        help="AWS profile name (default: np-farmers)",
    )
    parser.add_argument(
        "--region",
        type=str,
        default="us-east-1",
        help="AWS region name (default: us-east-1)",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Disable conversation history",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        help="Single prompt to send (if not provided, enters interactive mode)",
    )
    parser.add_argument(
        "--system-prompt",
        type=str,
        default=BedrockClient.DEFAULT_SYSTEM_PROMPT,
        help="Override the default system prompt",
    )
    parser.add_argument(
        "--model-arn",
        type=str,
        default=BedrockClient.DEFAULT_MODEL_ARN,
        help="Override the default model ARN",
    )
    return parser


def run_interactive_mode(client: BedrockClient, include_history: bool) -> None:
    print("Enter your prompts (Ctrl+D or Ctrl+C to exit):")
    try:
        while True:
            try:
                prompt = input("\nPrompt> ")
                if not prompt.strip():
                    continue

                response = client.invoke_model(prompt, include_history)
                print("\nResponse:", response.content)

            except (KeyboardInterrupt, EOFError):
                print("\nExiting...")
                break
            except Exception as e:
                print(f"\nError: {str(e)}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\nExiting...")


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    client = BedrockClient(
        profile_name=args.profile,
        region_name=args.region,
        model_arn=args.model_arn,
        system_prompt=args.system_prompt,
    )
    s3_analyzer = S3FileAnalyzer(client.session)
    client.register_tool(s3_analyzer.create_tool())

    try:
        if args.prompt:
            response = client.invoke_model(args.prompt, not args.no_history)
            print(response.content)
        else:
            run_interactive_mode(client, not args.no_history)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
