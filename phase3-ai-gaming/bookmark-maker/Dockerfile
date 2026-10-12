FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openscad potrace librsvg2-bin fonts-dejavu-core fonts-liberation curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pillow==11.0.0 onnxruntime==1.20.1 numpy==2.1.3

# Background-removal model for step 1 (IS-Net general use, the weights rembg ships). Baked in so it runs offline.
RUN mkdir -p /models \
    && curl -fsSL -o /models/isnet-general-use.onnx \
       https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx \
    && echo "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a  /models/isnet-general-use.onnx" | sha256sum -c -

RUN adduser --disabled-password --gecos '' appuser

COPY *.py page.html ./

USER appuser

EXPOSE 8105

CMD ["python", "app.py"]
