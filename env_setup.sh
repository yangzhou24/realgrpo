#!/bin/bash

# install torch
pip install torch==2.5.0 torchvision --index-url https://download.pytorch.org/whl/cu121

pip install packaging ninja && pip install flash-attn==2.7.0.post2 --no-build-isolation 

pip install -r requirements-lint.txt

# install fastvideo
pip install -e .

pip install ml-collections absl-py inflect==6.0.4
