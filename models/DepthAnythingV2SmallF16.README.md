---
tags:
- depth-estimation
library_name: coreml
license: apache-2.0
---

# Depth Anything V2 Core ML Models

Depth Anything V2 was introduced in [the paper of the same name](https://arxiv.org/abs/2406.09414) by Lihe Yang et al. It uses the same architecture as the original Depth Anything release, but uses synthetic data and a larger capacity teacher model to achieve much finer and robust depth predictions. The original Depth Anything model was introduced in the paper [Depth Anything: Unleashing the Power of Large-Scale Unlabeled Data](https://arxiv.org/abs/2401.10891) by Lihe Yang et al., and was first released in [this repository](https://github.com/LiheYoung/Depth-Anything).

## Model description

Depth Anything V2 leverages the [DPT](https://huggingface.co/docs/transformers/model_doc/dpt) architecture with a [DINOv2](https://huggingface.co/docs/transformers/model_doc/dinov2) backbone.

The model is trained on ~600K synthetic labeled images and ~62 million real unlabeled images, obtaining state-of-the-art results for both relative and absolute depth estimation.

<img src="https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/transformers/model_doc/depth_anything_overview.jpg"
alt="drawing" width="600"/>

<small> Depth Anything overview. Taken from the <a href="https://arxiv.org/abs/2401.10891">original paper</a>.</small>

## Evaluation - Variants

| Variant                                                 | Parameters | Size (MB) | Weight precision | Act. precision | abs-rel error | abs-rel reference |
| ------------------------------------------------------- | ---------: | --------: | ---------------- | -------------- | ------------: | ----------------: |
| [small-original](https://huggingface.co/pcuenq/Depth-Anything-V2-Small-hf) (PyTorch)                                 |      24.8M |      99.2 | Float32          | Float32        |               |                   |
| [DepthAnythingV2SmallF32](DepthAnythingV2SmallF32.mlpackage) |      24.8M |      99.2 | Float32          | Float32        |        0.0072 |    small-original |
| [DepthAnythingV2SmallF16](DepthAnythingV2SmallF16.mlpackage) |      24.8M |      49.8 | Float16          | Float16        |        0.0089 |    small-original |

Evaluated on 512 landscape images from the COCO dataset with aspect ratio similar to 4:3. Images were streched to a fixed size of 518x396, and the groundtruth corresponds to the results from the PyTorch model running on CUDA with `float32` precision. 

## Evaluation - Inference time

The following results use the small-float16 variant.

| Device               | OS   | Inference time (ms) | Dominant compute unit |
| -------------------- | ---- | ------------------: | --------------------- |
| iPhone 12 Pro Max    | 18.0 |               31.10 | Neural Engine         |
| iPhone 15 Pro Max    | 17.4 |               33.90 | Neural Engine         |
| MacBook Pro (M1 Max) | 15.0 |               32.80 | Neural Engine         |
| MacBook Pro (M3 Max) | 15.0 |               24.58 | Neural Engine         |


## Download

Install `huggingface-cli`

```bash
brew install huggingface-cli
```

To download one of the `.mlpackage` folders to the `models` directory:

```bash
huggingface-cli download \
  --local-dir models --local-dir-use-symlinks False \
  apple/coreml-depth-anything-v2-small \
  --include "DepthAnythingV2SmallF16.mlpackage/*"
```

To download everything, skip the `--include` argument.

## Integrate in Swift apps

The [`huggingface/coreml-examples`](https://github.com/huggingface/coreml-examples/blob/main/depth-anything-example/README.md) repository contains sample Swift code for `DepthAnythingV2SmallF16.mlpackage` and other models. See [the instructions there](https://github.com/huggingface/coreml-examples/tree/main/depth-anything-example) to build the demo app, which shows how to use the model in your own Swift apps.
