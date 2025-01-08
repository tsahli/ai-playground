from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

import requests

from tool import Tool


@dataclass
class DisputeResult:
    """Raw dispute data from API"""

    status: str
    data: Optional[Dict] = None
    error: Optional[str] = None


class DisputeAnalyzer:
    """Fetches dispute data from Checkout.com API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.sandbox.checkout.com"

    def get_dispute(self, dispute_id: str) -> DisputeResult:
        """Fetch dispute details from API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            response = requests.get(
                f"{self.base_url}/disputes/{dispute_id}",
                headers=headers,
            )

            if response.status_code == 200:
                # Format amounts to include decimal places
                data = response.json()
                if "amount" in data:
                    data["formatted_amount"] = f"{data['amount']/100:.2f}"
                if "payment" in data and "amount" in data["payment"]:
                    data["payment"][
                        "formatted_amount"
                    ] = f"{data['payment']['amount']/100:.2f}"

                return DisputeResult(status="success", data=data)
            else:
                return DisputeResult(
                    status="error",
                    error=f"API request failed with status {response.status_code}: {response.text}",
                )

        except Exception as e:
            return DisputeResult(status="error", error=str(e))

    def create_tool(self) -> Tool:
        """Create a Tool instance for the BedrockClient"""
        parameters = {
            "type": "object",
            "properties": {
                "dispute_id": {
                    "type": "string",
                    "description": "The ID of the dispute to analyze",
                }
            },
            "required": ["dispute_id"],
        }

        return Tool(
            name="analyze_dispute",
            description="""
            Fetch dispute details from Checkout.com API.
            Returns all available dispute data including:
            - Dispute category and reason code
            - Amount and currency
            - Status and deadlines
            - Required evidence types
            - Payment details

            Use this data along with reference documentation to provide analysis.
            """,
            parameters=parameters,
            function=lambda dispute_id: self.get_dispute(dispute_id).__dict__,
        )
