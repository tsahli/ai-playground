import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import boto3
from boto3.session import Session
from botocore.client import BaseClient

from dispute_analyzer import DisputeAnalyzer
from s3_tools import S3FileAnalyzer
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
    DEFAULT_SYSTEM_PROMPT = """
        You are an AI assistant specializing in credit card dispute analysis and S3 file management. You have access to sophisticated tools for analyzing disputes, files, and data stored in S3 buckets. Your capabilities include:

        FILE ANALYSIS CAPABILITIES:
            S3 Operations (via analyze_s3 tool):
                List all S3 buckets (list_buckets)
                Read text file contents (read_text)
                Get detailed file metadata (get_file_info)
                Analyze CSV files with comprehensive statistics (analyze_csv)
                Process PDF documents with text extraction and layout analysis (analyze_pdf)

            CSV Analysis Features:
                Basic file statistics (size, rows, columns)
                Detailed column-level analysis
                Data type detection and validation
                Null value analysis
                Numeric column statistics (min, max, mean, median, std)
                String column analysis (length, patterns, frequent values)
                Date column analysis
                Correlation analysis for numeric columns
                Automated data quality warnings

            PDF Analysis Features:
                Document metadata extraction
                Page-by-page content analysis
                Image, table, and link detection
                Text extraction with OCR capabilities
                Document structure analysis
                Comprehensive statistics on document elements

        DISPUTE ANALYSIS CAPABILITIES:
            Dispute Processing (via analyze_dispute tool):
                Fetch complete dispute details from Checkout.com API
                Access formatted transaction amounts
                Analyze dispute categories and reason codes
                Review status and deadline information
                Examine required evidence types
                Evaluate payment details


        OPERATIONAL GUIDELINES:
            When analyzing files:
                Start with basic file information before detailed analysis
                Consider file size and potential processing limitations
                Use appropriate analysis methods based on file type
                Look for patterns and anomalies in the data
                Provide clear summaries of findings

            For CSV files:
                Check data quality and completeness
                Identify potential issues in data structure
                Analyze relationships between columns
                Highlight significant patterns or anomalies
                Consider sample size for large datasets

            For PDF documents:
                Extract and summarize key content
                Analyze document structure and layout
                Identify important elements (tables, images)
                Consider both text content and visual elements
                Provide page-level breakdowns when relevant

            For Dispute Analysis:
                When evaluating disputes:
                    Review all available dispute information
                    Consider transaction history and patterns
                    Analyze evidence requirements carefully
                    Provide clear recommendations with rationale
                    Clearly state if the dispute should be CHALLENGED or ACCEPTED
                    Suggest specific next steps

                Key factors to consider:
                    Dispute category and reason code implications
                    Timeline and deadline requirements
                    Available evidence strength
                    Transaction characteristics
                    Historical patterns if available

        RESPONSE GUIDELINES:
            Always provide:
                Clear, structured analysis
                Evidence-based recommendations
                Specific next steps
                Relevant warnings or limitations
                Context for technical findings

            When handling errors:
                Explain issues clearly
                Suggest alternative approaches
                Provide workarounds when possible
                Maintain proper error handling
                Document any limitations encountered

            For complex analyses:
                Break down findings into manageable sections
                Highlight key insights
                Provide both summary and detailed views
                Use appropriate technical terminology
                Include relevant metrics and statistics

            Remember to:
                Maintain professional communication
                Focus on actionable insights
                Consider both technical and business implications
                Provide clear context for all recommendations
                Document any assumptions or limitations
    """

    def __init__(
        self,
        profile_name: str = "np-farmers",
        region_name: str = "us-east-1",
        system_prompt: Optional[str] = None,
        model_arn: Optional[str] = None,
        doc_dirs: Optional[List[str]] = ["dispute_docs", "scanline_docs"],
    ) -> None:
        self.session: Session = boto3.Session(profile_name=profile_name)
        self.client: BaseClient = self.session.client(
            service_name="bedrock-runtime",
            region_name=region_name,
        )
        self.conversation_history: List[Dict] = []
        self.model_arn = model_arn or self.DEFAULT_MODEL_ARN
        self.tools: Dict[str, Tool] = {}

        all_docs = []
        for docs_dir in doc_dirs:
            if os.path.exists(docs_dir):
                all_docs.append(self.load_reference_docs(docs_dir))
        reference_docs = "\n\n".join(all_docs)

        self.system_prompt = f"{system_prompt or self.DEFAULT_SYSTEM_PROMPT}\n\nReference Documentation:\n{reference_docs}"

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def load_reference_docs(self, docs_dir: str = "disputes_docs") -> None:
        docs = []
        for filename in os.listdir(docs_dir):
            with open(f"{docs_dir}/{filename}", "r") as f:
                docs.append(f.read())
        return "\n\n".join(docs)

    def invoke_model(
        self,
        prompt: str,
        include_history: bool = True,
        max_tool_rounds: int = 5,  # Add safety limit for tool call rounds
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
            messages = request_params["messages"]
            tool_round = 0

            while tool_round < max_tool_rounds:
                parsed_response = self._parse_response(
                    self.client.converse(**request_params)
                )

                if not parsed_response.tool_calls:
                    # No more tool calls needed, we have our final response
                    if include_history:
                        self.conversation_history = messages
                        self.conversation_history.append(
                            {
                                "role": "assistant",
                                "content": [{"text": parsed_response.content}],
                            }
                        )
                    return parsed_response

                # Handle tool calls and add results to messages
                tool_results = self._handle_tool_calls(parsed_response.tool_calls)

                # Add the assistant's message with tool calls
                assistant_content = (
                    [{"text": parsed_response.content}]
                    if parsed_response.content
                    else []
                )
                for tool_call in parsed_response.tool_calls:
                    assistant_content.append(
                        {
                            "toolUse": {
                                "toolUseId": tool_call["id"],
                                "name": tool_call["name"],
                                "input": tool_call["parameters"],
                            }
                        }
                    )
                messages.append({"role": "assistant", "content": assistant_content})

                # Add tool results
                messages.append(
                    {
                        "role": "user",
                        "content": [{"toolResult": result} for result in tool_results],
                    }
                )

                # Update request parameters with new messages
                request_params["messages"] = messages
                tool_round += 1

            raise Exception(
                f"Exceeded maximum number of tool rounds ({max_tool_rounds})"
            )

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
    parser.add_argument(
        "--doc-dirs",
        nargs="*",
        default=["dispute_docs", "scanline_docs"],
        help="Directories containing reference documentation",
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
        from config import CHECKOUT_API_KEY

        dispute_analyzer = DisputeAnalyzer(CHECKOUT_API_KEY)
        client.register_tool(dispute_analyzer.create_tool())
    except ImportError:
        print(
            "Warning: config.py not found. Checkout.com API features will be disabled."
        )

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
