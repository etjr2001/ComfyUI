import json
import os.path
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, HTTPException
import urllib
import websocket
from PIL import Image
import io
import base64
import copy
import uvicorn
import logging
from workflow import Workflow


workflow_json = {}
image_folder_path = None

server_address = "127.0.0.1:8188"
client_id = str(uuid.uuid4())

# Import json workflow
@asynccontextmanager
async def lifespan(app: FastAPI):
    global workflow_json
    global image_folder_path
    base_path = os.path.abspath(os.path.dirname(__file__))
    path = os.path.join(base_path, "workflow/ComfyUI-IDM-VTON.json")
    parent_dir = os.path.dirname(base_path)
    image_folder_path = os.path.join(parent_dir, "input")
    try:
        with open(path) as f:
            workflow_json = json.load(f)
        print("ComfyUI-IDM-VTON JSON workflow loaded successfully")
    except Exception as e:
        print(f"Failed to load ComfyUI-IDM-VTON JSON workflow")
    yield
    workflow_json.clear()


app = FastAPI(lifespan=lifespan)
logger = logging.getLogger('uvicorn.error')

@app.get("/")
async def read_root():
    return {"Hello": "World"}

@app.get("/workflow", response_model=Workflow)
async def read_workflow():
    return Workflow(workflow=workflow_json)
    
@app.post("/images/")
async def upload_images(file: UploadFile, type: str):
    contents = await file.read()
    content_type = file.content_type.split("/")[1]
    
    # Type: human or garment
    if type not in ["human", "garment"]:
        raise
    
    # Generate UUID for image uploaded and save to ComfyUI input folder
    image_name = f"{type}_{str(uuid.uuid4())}_{content_type}"
    file_location = f"{image_folder_path}/{image_name}.{content_type}"
    
    with open(file_location, "wb+") as file_object:
        file_object.write(contents)
    
    return image_name


@app.post("/generate")
async def generate(workflow: Workflow):
    """Starts ComfyUI workflow based on workflow provided

    Args:
        workflow (Workflow): JSON workflow in the format provided by GET /workflow request

    Returns:
        _type_: _description_
    """
    current_workflow_json = workflow.model_dump()
    human_image_name = current_workflow_json["workflow"]["4"]["inputs"]["image"]
    garment_image_name = current_workflow_json["workflow"]["8"]["inputs"]["image"]
    logger.info(f"POST /generate >> Human Image:{human_image_name}, Garment Image:{garment_image_name}")


    human_image_path = convert_image_name_to_filepath(human_image_name)
    garment_image_path = convert_image_name_to_filepath(garment_image_name)
    
    if not os.path.isfile(human_image_path):
        raise HTTPException(status_code=404, detail=f"Human image not found: {human_image_name}")
    
    if not os.path.isfile(garment_image_path):
        raise HTTPException(status_code=404, detail=f"Garment image not found: {garment_image_path}")
    
    
    current_workflow_json["workflow"]["4"]["inputs"]["image"] = human_image_path
    current_workflow_json["workflow"]["8"]["inputs"]["image"] = garment_image_path
    
    ws = websocket.WebSocket()
    
    ws.close()
    
    return workflow


# #TODO: change start workflow to accept JSON (pydantic model) instead of query parameters
# #TODO: debug the output of websocket
# @app.get("/generate")
# async def start_workflow(human_image_name: str, garment_image_name: str):
#     logger.info(f"start_workflow: {human_image_name}, {garment_image_name}")
#     human_image_path = convert_image_name_to_filepath(human_image_name)
#     garment_image_path = convert_image_name_to_filepath(garment_image_name)
#     if not os.path.isfile(human_image_path):
#         raise HTTPException(status_code=404, detail=f"Human image not found: {human_image_name}")
    
#     if not os.path.isfile(garment_image_path):
#         raise HTTPException(status_code=404, detail=f"Garment image not found: {garment_image_path}")
    
#     prompt = copy.deepcopy(workflow_json)
    
#     prompt["4"]["inputs"]["image"] = human_image_path
#     prompt["8"]["inputs"]["image"] = garment_image_path
    
#     ws = websocket.WebSocket()
#     ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
#     images = get_images(ws, prompt)
    
#     result = []
    
#     for node_id in images:
#         for image_data in images[node_id]:
#             result.append(image_to_base64(image_data))
            
            
#     ws.close()

    
#     return images


def convert_image_name_to_filepath(image_name: str):
    params = image_name.split("_")
    if len(params) >= 3:
        content_type = params[2]
    else:
        content_type = "invalid"
    return f"{image_folder_path}/{image_name}.{content_type}"




def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req =  urllib.request.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen("http://{}/view?{}".format(server_address, url_values)) as response:
        return response.read()

def get_history(prompt_id):
    with urllib.request.urlopen("http://{}/history/{}".format(server_address, prompt_id)) as response:
        return json.loads(response.read())

def get_images(ws, prompt):
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_images = {}
    current_node = ""
    while True:
        out = ws.recv()
        logger.debug('Current node', current_node)
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['prompt_id'] == prompt_id:
                    if data['node'] is None:
                        break #Execution is done
                    else:
                        current_node = data['node']
        else:
            if current_node == 'save_image':
                images_output = output_images.get(current_node, [])
                images_output.append(out[8:])
                output_images[current_node] = images_output

    return output_images


def image_to_base64(image: Image.Image, format="PNG"):
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format=format)
    return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")