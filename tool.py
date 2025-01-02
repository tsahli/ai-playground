from typing import Callable, Dict


class Tool:
    def __init__(
        self, name: str, description: str, parameters: Dict, function: Callable
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.function = function

    def to_dict(self) -> Dict:
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {"json": self.parameters},
            }
        }
