from pydantic import BaseModel, RootModel
from typing import Dict, Any


class Meta(BaseModel):
    title: str

class Node(BaseModel):
    inputs: Dict[str, Any]  # Not validating inputs because different nodes have different inputs
    class_type: str
    _meta: Meta


class Workflow(BaseModel):
    workflow: Dict[str, Node]