import json
import os.path
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import JSONResponse, Response
import urllib
import websocket
from PIL import Image
import io
import base64
import logging
from workflow import Workflow, Meta
import zipfile


default_workflow_json = {}
generate_mask_for_human_image_workflow_json = {}
generate_pose_for_human_image_workflow_json = {}
run_idm_vton_pipeline_workflow_json = {}
input_image_folder_path = None
output_image_folder_path = None


server_address = "127.0.0.1:8188"  # ComfyUI server address
client_id = str(uuid.uuid4())


# Import json workflow
@asynccontextmanager
async def lifespan(app: FastAPI):
    global default_workflow_json
    global generate_mask_for_human_image_workflow_json
    global generate_pose_for_human_image_workflow_json
    global run_idm_vton_pipeline_workflow_json
    global input_image_folder_path
    global output_image_folder_path
    base_path = os.path.abspath(os.path.dirname(__file__))
    parent_dir = os.path.dirname(base_path)
    input_image_folder_path = os.path.join(parent_dir, "input")
    output_image_folder_path = os.path.join(parent_dir, "output")

    workflow_path = os.path.join(base_path, "workflow")

    def load_workflow_json(workflow_path, json_file_name):
        path = os.path.join(workflow_path, json_file_name)
        try:
            with open(path, 'r') as f:
                workflow_json = json.load(f)
            logger.info(f"{json_file_name} loaded successfully")
            return workflow_json
        except Exception as e:
            logger.error(f"Failed to load {json_file_name}")
            logger.error(e)
            return None

    default_workflow_json = load_workflow_json(workflow_path, "ComfyUI-IDM-VTON.json")
    generate_mask_for_human_image_workflow_json = load_workflow_json(workflow_path, "generate_mask_for_human_image.json")
    generate_pose_for_human_image_workflow_json = load_workflow_json(workflow_path, "generate_pose_for_human_image.json")
    run_idm_vton_pipeline_workflow_json = load_workflow_json(workflow_path, "run_idm_vton_pipeline.json")

    yield
    default_workflow_json.clear()
    generate_mask_for_human_image_workflow_json.clear()
    generate_pose_for_human_image_workflow_json.clear()
    run_idm_vton_pipeline_workflow_json.clear()


app = FastAPI(lifespan=lifespan)
logger = logging.getLogger('uvicorn.error')


@app.get("/")
async def read_root():
    return {"Hello": "World"}


@app.get("/workflows", response_model=Workflow)
async def read_workflow(workflow: str | None = None):
    """Get workflow from backend server

    Args:
        workflow (str | None, optional): Type of workflow: mask, pose, pipeline. Defaults to None.

    Returns:
        Workflow: JSON workflow requested.
    """
    if workflow:
        if (workflow == "mask"):
            return Workflow(workflow=generate_mask_for_human_image_workflow_json,
                            _meta=Meta(title="mask"))
        if (workflow == "pose"):
            return Workflow(workflow=generate_pose_for_human_image_workflow_json,
                            _meta=Meta(title="pose"))
        if (workflow == "pipeline"):
            return Workflow(workflow=run_idm_vton_pipeline_workflow_json,
                            _meta=Meta(title="pipeline"))
    return Workflow(workflow=default_workflow_json,
                    _meta=Meta(title="default"))


@app.post("/images")
async def upload_images(file: UploadFile):
    """Upload images to ComfyUI Server

    Args:
        file (UploadFile): image in upload file format

    Returns:
        dict: UUID of the image stored in ComfyUI server
    """
    contents = await file.read()
    content_type = file.content_type.split("/")[1]

    # Generate UUID for image uploaded and save to ComfyUI input folder
    image_uuid = str(uuid.uuid4())
    file_location = f"{input_image_folder_path}/{image_uuid}.{content_type}"

    with open(file_location, "wb+") as file_object:
        file_object.write(contents)

    return JSONResponse(content={
        "image_uuid": image_uuid
        })


@app.get("/images/{image_uuid}")
async def download_images(image_uuid: str):
    """Download image from ComfyUI Server

    Args:
        image_uuid (str): UUID of the image to be downloaded

    Raises:
        HTTPException: 404 Image not found

    Returns:
        Response: Zip of images requested
    """
    logger.info(f"GET /images image_uuid: {image_uuid}")
    file_paths = convert_image_uuid_to_filepaths(image_uuid)
    return zipfiles(file_paths)


def zipfiles(filenames):
    zip_filename = "images.zip"
    s = io.BytesIO()
    zf = zipfile.ZipFile(s, "w")

    for fpath in filenames:
        fdir, fname = os.path.split(fpath)

        zf.write(fpath, fname)

    zf.close()

    response = Response(s.getvalue(),
                        media_type="application/x-zip-compressed",
                        headers={
                            "Content-Disposition": f"attachment;filename={zip_filename}"
                        })

    return response


@app.post("/run")
async def run_workflow(workflow: Workflow):
    """Run workflow provided. Meta title provides type of workflow

    Args:
        workflow (Workflow): JSON workflow to be run on ComfyUI

    Raises:
        HTTPException: Invalid workflow type or empty workflow

    Returns:
        output_uuid (str): UUID of image generated. Used to download image by GET /images request
    """
    output_uuid = None
    meta_title = workflow.meta.title
    logger.info(f"run_workflow, meta_title = {meta_title}")
    if (meta_title == None or workflow == None):
        raise HTTPException(status_code=400, detail="Invalid workflow")
    if (meta_title == "mask"):
        output_uuid = run_mask_workflow(workflow)
    if (meta_title == "pose"):
        output_uuid = run_pose_workflow(workflow)
    if (meta_title == "pipeline"):
        output_uuid = run_pipeline_workflow(workflow)
    if (meta_title == "default"):
        output_uuid = run_default_workflow(workflow)
    return JSONResponse(content={
        "image_uuid": output_uuid
        })


def run_mask_workflow(mask_workflow: Workflow):
    """Run workflow to generate mask from human image

    Args:
        mask_workflow (Workflow): JSON workflow to generate mask provided by GET /workflows?workflow=mask request

    Returns:
        filename_prefix (str): UUID of mask image generated. Used to download image by GET /images request
    """
    current_workflow_json = mask_workflow.model_dump(by_alias=True)
    human_image_uuid = current_workflow_json["workflow"]["1"]["inputs"]["image"]
    human_image_path = convert_image_uuid_to_filepaths(human_image_uuid)

    if not os.path.isfile(human_image_path):
        raise HTTPException(status_code=404, detail=f"Human image not found: {human_image_uuid}")

    current_workflow_json["workflow"]["1"]["inputs"]["image"] = human_image_path

    filename_prefix = str(uuid.uuid4())

    current_workflow_json["workflow"]["6"]["inputs"]["filename_prefix"] = filename_prefix

    run_prompt(current_workflow_json)

    return filename_prefix


def run_pose_workflow(pose_workflow: Workflow):
    """Run workflow to generate pose from human image

    Args:
        pose_workflow (Workflow): JSON workflow to generate pose provided by GET /workflows?workflow=pose request

    Returns:
        filename_prefix (str): UUID of pose image generated. Used to download image by GET /images request
    """
    current_workflow_json = pose_workflow.model_dump(by_alias=True)
    human_image_uuid = current_workflow_json["workflow"]["1"]["inputs"]["image"]
    human_image_path = convert_image_uuid_to_filepaths(human_image_uuid)

    if not os.path.isfile(human_image_path):
        raise HTTPException(status_code=404, detail=f"Human image not found: {human_image_uuid}")

    current_workflow_json["workflow"]["1"]["inputs"]["image"] = human_image_path

    resolution = current_workflow_json["workflow"]["2"]["inputs"]["resolution"]
    current_workflow_json["workflow"]["2"]["inputs"]["resolution"] = round_down_to_multiple(resolution, 8)

    filename_prefix = str(uuid.uuid4())

    current_workflow_json["workflow"]["3"]["inputs"]["filename_prefix"] = filename_prefix

    run_prompt(current_workflow_json)

    return filename_prefix


def run_pipeline_workflow(pipeline_workflow: Workflow):
    """Run pipeline using generated masking and pose estimation. Requires all images to already be generated.

    Args:
        pipeline_workflow (Workflow): JSON workflow to generate tryon provided by GET /workflows?workflow=pipeline request

    Returns:
        filename_prefix (str): UUID of tryon image generated. Used to download image by GET /images request
    """
    current_workflow_json = pipeline_workflow.model_dump(by_alias=True)
    human_image_uuid = current_workflow_json["workflow"]["1"]["inputs"]["image"]
    human_image_path = convert_image_uuid_to_filepaths(human_image_uuid)

    if not os.path.isfile(human_image_path):
        raise HTTPException(status_code=404, detail=f"Human image not found: {human_image_uuid}")

    current_workflow_json["workflow"]["1"]["inputs"]["image"] = human_image_path


    pose_image_uuid = current_workflow_json["workflow"]["2"]["inputs"]["image"]
    pose_image_path = convert_image_uuid_to_filepaths(pose_image_uuid)

    if not os.path.isfile(pose_image_path):
        raise HTTPException(status_code=404, detail=f"Pose image not found: {pose_image_uuid}")

    current_workflow_json["workflow"]["2"]["inputs"]["image"] = pose_image_path


    mask_image_uuid = current_workflow_json["workflow"]["3"]["inputs"]["image"]
    mask_image_path = convert_image_uuid_to_filepaths(mask_image_uuid)

    if not os.path.isfile(mask_image_path):
        raise HTTPException(status_code=404, detail=f"Mask image not found: {mask_image_uuid}")

    current_workflow_json["workflow"]["3"]["inputs"]["image"] = mask_image_path


    garment_image_uuid = current_workflow_json["workflow"]["4"]["inputs"]["image"]
    garment_image_path = convert_image_uuid_to_filepaths(garment_image_uuid)

    if not os.path.isfile(garment_image_path):
        raise HTTPException(status_code=404, detail=f"Garment image not found: {garment_image_uuid}")

    current_workflow_json["workflow"]["4"]["inputs"]["image"] = garment_image_path

    height = current_workflow_json["workflow"]["6"]["inputs"]["height"]
    current_workflow_json["workflow"]["6"]["inputs"]["height"] = round_down_to_multiple(height, 8)

    width = current_workflow_json["workflow"]["6"]["inputs"]["width"]
    current_workflow_json["workflow"]["6"]["inputs"]["width"] = round_down_to_multiple(width, 8)


    filename_prefix = str(uuid.uuid4())

    current_workflow_json["workflow"]["7"]["inputs"]["filename_prefix"] = filename_prefix

    # Run updated IDM-VTON_V2
    current_workflow_json["workflow"]["6"]["class_type"] = "IDM-VTON_V2"

    run_prompt(current_workflow_json)

    return filename_prefix


def run_default_workflow(default_workflow: Workflow):
    """Run default workflow

    Args:
        default_workflow (Workflow): default JSON workflow in the format provided by GET /workflows request

    Returns:
        filename_prefix (str): UUID of image generated. Used to download image by GET /images request
    """
    current_workflow_json = default_workflow.model_dump(by_alias=True)
    human_image_uuid = current_workflow_json["workflow"]["4"]["inputs"]["image"]
    garment_image_uuid = current_workflow_json["workflow"]["8"]["inputs"]["image"]
    logger.info(f"POST /generate >> Human Image:{human_image_uuid}, Garment Image:{garment_image_uuid}")


    human_image_path = convert_image_uuid_to_filepaths(human_image_uuid)
    garment_image_path = convert_image_uuid_to_filepaths(garment_image_uuid)

    if not os.path.isfile(human_image_path):
        raise HTTPException(status_code=404, detail=f"Human image not found: {human_image_uuid}")

    if not os.path.isfile(garment_image_path):
        raise HTTPException(status_code=404, detail=f"Garment image not found: {garment_image_path}")


    current_workflow_json["workflow"]["4"]["inputs"]["image"] = human_image_path

    resolution = current_workflow_json["workflow"]["5"]["inputs"]["resolution"]
    current_workflow_json["workflow"]["5"]["inputs"]["resolution"] = round_down_to_multiple(resolution, 8)

    current_workflow_json["workflow"]["8"]["inputs"]["image"] = garment_image_path

    height = current_workflow_json["workflow"]["11"]["inputs"]["height"]
    current_workflow_json["workflow"]["11"]["inputs"]["height"] = round_down_to_multiple(height, 8)

    width = current_workflow_json["workflow"]["11"]["inputs"]["width"]
    current_workflow_json["workflow"]["11"]["inputs"]["width"] = round_down_to_multiple(width, 8)

    # Run updated IDM-VTON_V2
    current_workflow_json["workflow"]["6"]["class_type"] = "IDM-VTON_V2"

    filename_prefix = str(uuid.uuid4())

    current_workflow_json["workflow"]["13"]["inputs"]["filename_prefix"] = filename_prefix

    run_prompt(current_workflow_json)

    return filename_prefix


def round_down_to_multiple(value: int, multiple: int):
    return (value // multiple) * multiple


def run_prompt(workflow_json):
    logger.info(f"run_prompt: {workflow_json}")

    ws = websocket.WebSocket()

    ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))

    response = queue_prompt(workflow_json["workflow"])

    prompt_id = response['prompt_id']

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

    ws.close()


def convert_image_uuid_to_filepaths(image_uuid: str):
    logger.info(f"convert_image_uuid_to_filepath: {image_uuid}")

    filepaths = [input_image_folder_path, output_image_folder_path]

    uuid = image_uuid
    prefixed = []
    for filepath in filepaths:
        for entry in os.listdir(filepath):
            fullpath = os.path.join(filepath, entry)
            if entry.startswith(uuid) and os.path.isfile(fullpath):
                prefixed.append(fullpath)

    if not prefixed:
        raise HTTPException(status_code=404, detail="Image not found")
    return prefixed


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
