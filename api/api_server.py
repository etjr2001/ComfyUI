import json
import os.path
from contextlib import asynccontextmanager
from fastapi import FastAPI



workflow_json = {}

# Import json workflow
@asynccontextmanager
async def lifespan(app: FastAPI):
    global workflow_json
    base_path = os.path.abspath(os.path.dirname(__file__))
    path = os.path.join(base_path, "workflow/ComfyUI-IDM-VTON.json")
    try:
        with open(path) as f:
            workflow_json = json.load(f)
        print("ComfyUI-IDM-VTON JSON workflow loaded successfully")
    except Exception as e:
        print(f"Failed to load ComfyUI-IDM-VTON JSON workflow")
    yield
    workflow_json.clear()


app = FastAPI(lifespan=lifespan)

@app.get("/")
async def read_root():
    print(workflow_json)
    return {"Hello": "World"}

@app.get("/workflow")
async def read_workflow():
    return {"workflow": workflow_json}
    
