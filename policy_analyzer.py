from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

import requests

from tool import Tool


@dataclass
class PolicyResult:
    """Raw policy data from API"""

    status: str
    data: Optional[Dict] = None
    error: Optional[str] = None


class PolicyAnalyzer:
    """Fetches policy data from Sure API"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.soda14.com/api/management/v1"

    def get_policy(self, policy_id: str) -> PolicyResult:
        """Fetch policy details from API"""
        try:
            headers = {
                "x-space": "farmers",
                "Authorization": f"Bearer {self.api_key}",
            }

            response = requests.request(
                "GET",
                f"{self.base_url}/policies/{policy_id}",
                headers=headers,
                data={},
                files={},
            )

            if response.status_code == 200:
                data = response.json()

                return PolicyResult(status="success", data=data)
            else:
                return PolicyResult(
                    status="error",
                    error=f"API request failed with status {response.status_code}: {response.text}",
                )

        except Exception as e:
            return PolicyResult(status="error", error=str(e))

    def create_tool(self) -> Tool:
        """Create a Tool instance for the PolicyAnalyzer"""
        parameters = {
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "The ID of the policy to analyze",
                }
            },
            "required": ["policy_id"],
        }

        return Tool(
            name="analyze_policy",
            description="""
            Fetch policy details from Sure API.
            Returns comprehensive policy data including:
            - Policy details and status
            - Client information
            - Billing history and payment methods
            - Vehicle and driver information
            - Documents and renewals
            - Service dates and auto-renewal status

            Use this data to analyze policy status, billing patterns, and coverage details.
            """,
            parameters=parameters,
            function=lambda policy_id: self.get_policy(policy_id).__dict__,
        )
