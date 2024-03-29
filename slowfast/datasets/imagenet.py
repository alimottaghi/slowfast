# Copyright (c) Facebook, Inc. and its affiliates.

import json
import numpy as np
import pandas as pd
import os
import random
from datetime import datetime
import re
import torch
import torch.utils.data

# import cv2
from iopath.common.file_io import g_pathmgr
from PIL import Image
from torchvision import transforms as transforms_tv

import logging
pil_logger = logging.getLogger('PIL')
pil_logger.setLevel(logging.WARNING)

import slowfast.datasets.transform as transform
import slowfast.utils.logging as mylogging

from .build import DATASET_REGISTRY
from .transform import transforms_imagenet_train

logger = mylogging.get_logger(__name__)


@DATASET_REGISTRY.register()
class Imagenet(torch.utils.data.Dataset):
    """ImageNet dataset."""

    def __init__(self, cfg, mode, num_retries=10):
        self.num_retries = num_retries
        self.cfg = cfg
        self.mode = mode
        self.data_path = cfg.DATA.PATH_TO_DATA_DIR
        assert mode in [
            "train",
            "lab", 
            "unl",
            "val",
            "test",
        ], "Split '{}' not supported for ImageNet".format(mode)
        logger.info("Constructing ImageNet {}...".format(mode))
        if cfg.DATA.PATH_TO_PRELOAD_IMDB == "":
            self._construct_imdb()
        else:
            self._load_imdb()

    def _load_imdb(self):
        if hasattr(self.cfg.DATA, 'IMDB_FILES'):
            if self.mode in ['lab', 'unl']:
                imdb_files = [f"{path}.csv" for path in getattr(self.cfg.DATA.IMDB_FILES, 'TRAIN')]
            else:
                imdb_files = [f"{path}.csv" for path in getattr(self.cfg.DATA.IMDB_FILES, self.mode.upper())]
        else:
            imdb_files = [f"{self.mode}.csv"]
        all_imdb = []
        all_labels = []
        self._class_ids = []
        for imdb_file in imdb_files:
            split_path = os.path.join(
                self.cfg.DATA.PATH_TO_PRELOAD_IMDB, imdb_file
            )
            with g_pathmgr.open(split_path, "r") as f:
                rows = f.read().splitlines()
            if hasattr(self.cfg.DATA, 'SAMPLE_RATIO') and self.cfg.DATA.SAMPLE_RATIO < 1.0:
                if self.mode in ["train", "lab", "unl"]:
                    random.seed(self.cfg.RNG_SEED)
                    rows = random.sample(rows, int(len(rows) * self.cfg.DATA.SAMPLE_RATIO))
            for clip_idx, path_label in enumerate(rows):
                fetch_info = path_label.split(
                    self.cfg.DATA.PATH_LABEL_SEPARATOR
                )
                if len(fetch_info) == 2:
                    path, label = fetch_info
                elif len(fetch_info) == 3:
                    path, fn, label = fetch_info
                elif len(fetch_info) == 1:
                    path, label = fetch_info[0], 0
                else:
                    raise RuntimeError(
                        "Failed to parse video fetch {} info {} retries.".format(
                            path_label, fetch_info
                        )
                    )
                if label not in self._class_ids:
                    self._class_ids.append(label)
                all_imdb.append(
                    {"im_path": os.path.join(self.cfg.DATA.PATH_PREFIX, path), 
                    "class": int(label)})
                all_labels.append(int(label))

        random.seed(self.cfg.RNG_SEED)
        all_cases = list(range(len(all_imdb)))
        if self.cfg.ADAPTATION.SEMI_SUPERVISED.NUM_SHOTS:
            lab_cases = []
            for class_id in self._class_ids:
                class_cases = [i for i, c in enumerate(all_labels) if c == int(class_id)]
                if len(class_cases) < self.cfg.ADAPTATION.SEMI_SUPERVISED.NUM_SHOTS:
                    lab_class = random.choices(class_cases, k=self.cfg.ADAPTATION.SEMI_SUPERVISED.NUM_SHOTS)
                    logger.warning(f"Class {class_id} has less than {self.cfg.ADAPTATION.SEMI_SUPERVISED.NUM_SHOTS} samples")
                else:
                    lab_class = random.sample(class_cases, self.cfg.ADAPTATION.SEMI_SUPERVISED.NUM_SHOTS)
                lab_cases.extend(lab_class)
            batch_size = self.cfg.TRAIN.BATCH_SIZE  # int(self.cfg.TRAIN.BATCH_SIZE / max(1, self.cfg.NUM_GPUS))
            if len(lab_cases) < batch_size:
                lab_cases = random.choices(lab_cases, k=batch_size)
        else:
            num_cases = len(all_cases)
            num_lab = int(self.cfg.ADAPTATION.SEMI_SUPERVISED.LAB_RATIO*num_cases)
            lab_cases = random.sample(all_cases, num_lab)
        unl_cases = sorted(list(set(all_cases).difference(lab_cases)))

        if self.mode=='lab':
            split_cases = lab_cases
        elif self.mode=='unl':
            split_cases = unl_cases
        else:
            split_cases = all_cases

        self._imdb = [all_imdb[case] for case in split_cases]
        logger.info("IMDB loaded: {}".format(split_path))
        logger.info("Number of images: {}".format(len(self._imdb)))
        logger.info("Number of classes: {}".format(len(self._class_ids)))
        # Write the imdb to disk
        split_path = os.path.join(self.cfg.OUTPUT_DIR, f"{self.mode}.csv")
        pd.DataFrame(self._imdb).to_csv(split_path, index=False, header=False, sep=" ")

    def _construct_imdb(self):
        """Constructs the imdb."""
        # Compile the split data path
        split_path = os.path.join(self.data_path, self.mode)
        logger.info("{} data path: {}".format(self.mode, split_path))
        # Images are stored per class in subdirs (format: n<number>)
        split_files = g_pathmgr.ls(split_path)
        self._class_ids = sorted(
            f for f in split_files #  if re.match(r"^n[0-9]+$", f)
        )
        # Map ImageNet class ids to contiguous ids
        self._class_id_cont_id = {v: i for i, v in enumerate(self._class_ids)}
        # Construct the image db
        self._imdb = []
        for class_id in self._class_ids:
            cont_id = self._class_id_cont_id[class_id]
            im_dir = os.path.join(split_path, class_id)
            for im_name in g_pathmgr.ls(im_dir):
                im_path = os.path.join(im_dir, im_name)
                self._imdb.append({"im_path": im_path, "class": cont_id})
        logger.info("Number of images: {}".format(len(self._imdb)))
        logger.info("Number of classes: {}".format(len(self._class_ids)))
        # Write the imdb to disk
        split_path = os.path.join(self.cfg.OUTPUT_DIR, f"{self.mode}.csv")
        pd.DataFrame(self._imdb).to_csv(split_path, index=False, header=False, sep=" ")

    def load_image(self, im_path):
        """Prepares the image for network input with format of CHW RGB float"""
        with g_pathmgr.open(im_path, "rb") as f:
            with Image.open(f) as im:
                im = im.convert("RGB")
        im = torch.from_numpy(np.array(im).astype(np.float32) / 255.0)
        # H W C to C H W
        im = im.permute([2, 0, 1])
        return im

    def _prepare_im_tf(self, im_path):
        with g_pathmgr.open(im_path, "rb") as f:
            with Image.open(f) as im:
                im = im.convert("RGB")
        # Convert HWC/BGR/int to HWC/RGB/float format for applying transforms
        train_size, test_size = (
            self.cfg.DATA.TRAIN_CROP_SIZE,
            self.cfg.DATA.TEST_CROP_SIZE,
        )

        aug_transform_train = transforms_imagenet_train(
            img_size=(train_size, train_size),
            color_jitter=self.cfg.AUG.COLOR_JITTER,
            grayscale=self.cfg.AUG.GRAYSCALE,
            gaussian_blur=self.cfg.AUG.GAUSSIAN_BLUR,
            auto_augment=self.cfg.AUG.AA_TYPE,
            interpolation=self.cfg.AUG.INTERPOLATION,
            re_prob=self.cfg.AUG.RE_PROB,
            re_mode=self.cfg.AUG.RE_MODE,
            re_count=self.cfg.AUG.RE_COUNT,
            mean=self.cfg.DATA.MEAN,
            std=self.cfg.DATA.STD,
        )
        t = []
        size = int((256 / 224) * test_size)
        t.append(
            transforms_tv.Resize(
                size, interpolation=3
            ),  # to maintain same ratio w.r.t. 224 images
        )
        t.append(transforms_tv.CenterCrop(test_size))
        t.append(transforms_tv.ToTensor())
        t.append(
            transforms_tv.Normalize(self.cfg.DATA.MEAN, self.cfg.DATA.STD)
        )
        aug_transform_val = transforms_tv.Compose(t)
        if self.cfg.ADAPTATION.ENABLE and self.mode in ["train", "lab", "unl"]:
            return [aug_transform_train(im), aug_transform_val(im)]
        elif self.mode in ["train", "lab", "unl"]:
            return [aug_transform_train(im)]
        else:
            return [aug_transform_val(im)]

    def __load__(self, index):
        try:
            # Load the image
            im_path = self._imdb[index]["im_path"]
            # Prepare the image for training / testing
            if self.cfg.AUG.ENABLE:
                if self.mode == "train" and self.cfg.AUG.NUM_SAMPLE > 1:
                    im = []
                    for _ in range(self.cfg.AUG.NUM_SAMPLE):
                        crop = self._prepare_im_tf(im_path)
                        im.append(crop)
                    return im
                else:
                    im = self._prepare_im_tf(im_path)
                    return im
            else:
                im = self._prepare_im_res(im_path)
                return im
        except Exception:
            return None

    def __getitem__(self, index):
        # if the current image is corrupted, load a different image.
        for _ in range(self.num_retries):
            im = self.__load__(index)
            # Data corrupted, retry with a different image.
            if im is None:
                index = random.randint(0, len(self._imdb) - 1)
            else:
                break
        # Retrieve the label
        label = self._imdb[index]["class"]
        if False and isinstance(im, list):
            label = [label for _ in range(len(im))]
            # dummy = [torch.Tensor() for _ in range(len(im))]
            return im, label, index, {}
        else:
            # dummy = torch.Tensor()
            return im, label, index, {}

    def __len__(self):
        return len(self._imdb)
