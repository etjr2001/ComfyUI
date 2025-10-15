from pydantic import BaseModel, Field
from typing import Dict, Any


class Meta(BaseModel):
    title: str

class Node(BaseModel):
    inputs: Dict[str, Any]  # Not validating inputs because different nodes have different inputs
    class_type: str
    meta: Meta = Field(..., alias="_meta")

class Workflow(BaseModel):
    workflow: Dict[str, Node]
    meta: Meta = Field(..., alias="_meta")
