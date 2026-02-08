import os
from io import BytesIO

import boto3
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from PIL import Image

app = FastAPI()

def r2_client():
    endpoint = os.environ.get("R2_ENDPOINT")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")

    if not endpoint or not access_key or not secret_key:
        raise RuntimeError("Missing one of R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY")

    # Cloudflare R2 uses S3-compatible API; region can be anything but "auto" is common
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/r2/get-image")
def get_image(key: str):
    """
    Fetch an image from R2 and return it as PNG (for testing).
    Example key: raw/TEST-001/original.png
    """
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        raise HTTPException(status_code=500, detail="Missing R2_BUCKET")

    s3 = r2_client()

    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = obj["Body"].read()
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"R2 get_object failed: {e}")

    # Convert to PNG so browser always displays consistently
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
        out = BytesIO()
        img.save(out, format="PNG")
        return Response(content=out.getvalue(), media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a valid image or Pillow failed: {e}")
