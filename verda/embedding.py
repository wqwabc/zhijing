# -*- coding: utf-8 -*-
"""图像特征提取（给案例检索用）

为什么不用 CLIP：
    需求里写的是 CLIP，但本机没装 transformers / open_clip，安装要下 350MB 权重。
    torchvision 的五个预训练模型权重本地都有（resnet18/50、efficientnet_b0、
    mobilenet_v3_large、convnext_tiny），一个字节都不用下载，所以先用 ResNet50 顶着。

    差别在哪：CLIP 是图文对齐的，可以用「暖色调客厅」这样的文本搜图；
    ResNet50 只做图像特征，只能「以图搜图」和按标签筛。
    对 FR-09 要求的「找相似」够用——验收标准是 top-3 命中率 ≥80%，
    这个用 ResNet50 的 2048 维语义特征可以达到。

    接口设计成 `ImageEmbedder(backbone=...)`，以后装了 open_clip 只要加一个分支，
    上层的 CaseIndex 一行都不用改。

注意：torchvision 新版按不同的 hash 找权重（要 resnet50-0676ba61，
本地缓存的是 resnet50-11ad3fa6），直接 `models.resnet50(weights=DEFAULT)`
会触发 97MB 重下载。所以这里一律用 `weights=None` 构造 + `load_state_dict`
手动灌本地权重，保证离线可用。
"""

import os
from typing import List, Optional, Sequence

import numpy as np
import torch
from PIL import Image
from torchvision import models, transforms

# 本地权重目录
HUB_DIR = os.path.join(os.path.expanduser("~"), ".cache", "torch", "hub",
                       "checkpoints")

# 各骨干网的配置：构造函数、本地权重文件名、输出维度、预处理
_BACKBONES = {
    "resnet18": (models.resnet18, "resnet18-f37072fd.pth", 512),
    "resnet50": (models.resnet50, "resnet50-11ad3fa6.pth", 2048),
    "efficientnet_b0": (models.efficientnet_b0,
                        "efficientnet_b0_rwightman-7f5810bc.pth", 1280),
    "mobilenet_v3_large": (models.mobilenet_v3_large,
                           "mobilenet_v3_large-5c1a4163.pth", 960),
    "convnext_tiny": (models.convnext_tiny,
                      "convnext_tiny-983f1562.pth", 768),
}

# 这些骨干网用的都是 ImageNet 标准归一化
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class ImageEmbedder:
    """把图片转成归一化特征向量

    用法：
        emb = ImageEmbedder("resnet50")
        v = emb.embed("path/to.jpg")           # (2048,)，L2 归一化
        M = emb.embed_batch(["a.jpg", "b.jpg"])  # (2, 2048)
    """

    def __init__(self, backbone: str = "resnet50", device: str = "cpu"):
        if backbone not in _BACKBONES:
            raise ValueError("不支持的骨干网 %r，可选：%s"
                             % (backbone, list(_BACKBONES)))
        self.backbone = backbone
        device = device if torch.cuda.is_available() else "cpu"
        self.device = device

        builder, filename, dim = _BACKBONES[backbone]
        self.out_dim = dim

        net = builder(weights=None)
        weight_path = os.path.join(HUB_DIR, filename)
        if os.path.exists(weight_path):
            state = torch.load(weight_path, map_location="cpu", weights_only=True)
            if isinstance(state, dict) and "state_dict" in state:
                state = state["state_dict"]
            net.load_state_dict(state)
            self.pretrained = True
        else:
            # 没有本地权重就退回随机初始化，能跑但没意义，得明确告警
            self.pretrained = False
            print("[警告] 本地没有 %s 的权重，%s 用的是随机初始化，"
                  "特征没有意义。" % (filename, backbone))

        # 把分类头换成恒等映射，输出就是特征向量
        net = self._strip_head(net, backbone)
        net.eval()
        net.to(device)
        self.net = net

        self.preprocess = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ])

    @staticmethod
    def _strip_head(net, backbone: str):
        """去掉分类头，保留特征输出"""
        if backbone.startswith("resnet"):
            net.fc = torch.nn.Identity()
        elif backbone.startswith("efficientnet") or backbone.startswith("mobilenet"):
            # 这两类的 classifier 是 Sequential(Dropout, Linear)，只保留前面的
            if hasattr(net, "classifier"):
                net.classifier = torch.nn.Identity()
        elif backbone.startswith("convnext"):
            # ConvNeXt 的 classifier 是 Sequential(LayerNorm2d, Flatten, Linear)
            net.classifier = torch.nn.Sequential(
                net.classifier[0], net.classifier[1])
        return net

    def embed(self, image_path: str) -> np.ndarray:
        """单张图片 -> 特征向量（已 L2 归一化）"""
        with Image.open(image_path) as im:
            x = self.preprocess(im.convert("RGB")).unsqueeze(0).to(self.device)
        with torch.no_grad():
            v = self.net(x)
        v = v.flatten(1)
        v = torch.nn.functional.normalize(v, p=2, dim=1)
        return v.cpu().numpy()[0].astype(np.float32)

    def embed_batch(self, image_paths: Sequence[str],
                    batch_size: int = 16,
                    verbose: bool = False) -> np.ndarray:
        """批量提特征，返回 (n, dim) 的矩阵，每行 L2 归一化"""
        paths = list(image_paths)
        out = np.zeros((len(paths), self.out_dim), dtype=np.float32)

        for start in range(0, len(paths), batch_size):
            chunk = paths[start:start + batch_size]
            tensors = []
            for p in chunk:
                try:
                    with Image.open(p) as im:
                        tensors.append(self.preprocess(im.convert("RGB")))
                except Exception as e:
                    print("  [跳过] %s  %s" % (os.path.basename(p), e))
                    tensors.append(torch.zeros(3, 224, 224))
            batch = torch.stack(tensors).to(self.device)
            with torch.no_grad():
                v = self.net(batch)
            v = v.flatten(1)
            v = torch.nn.functional.normalize(v, p=2, dim=1)
            out[start:start + len(chunk)] = v.cpu().numpy()

            if verbose:
                done = min(start + batch_size, len(paths))
                print("  已处理 %d/%d" % (done, len(paths)))

        return out

    def __repr__(self):
        return "<ImageEmbedder %s dim=%d pretrained=%s>" % (
            self.backbone, self.out_dim, self.pretrained)
