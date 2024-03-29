#!/usr/bin/env python3
# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved.
"""Wrapper to train and test a video classification model."""
import os
from slowfast.config.defaults import assert_and_infer_cfg
from slowfast.utils.misc import launch_job
from slowfast.utils.parser import load_config, parse_args

from test_net import test
from train import train
from visualization import visualize
from extract_features import extract
from train_adamatch import train as adamatch
from train_adaembed import train as adaembed
from mme import train as mme
from train_mcd import train as mcd

def main():
    """
    Main function to spawn the train and test process.
    """
    args = parse_args()
    cfg = load_config(args)
    cfg = assert_and_infer_cfg(cfg)
    os.system(f'cp {args.cfg_file} {os.path.join(cfg.OUTPUT_DIR,"config.yaml")}')

    # Perform training.
    if cfg.TRAIN.ENABLE:
        if cfg.ADAPTATION.ENABLE:
            if cfg.ADAPTATION.ADAPTATION_TYPE == "AdaEmbed":
                launch_job(cfg=cfg, init_method=args.init_method, func=adaembed)
            elif cfg.ADAPTATION.ADAPTATION_TYPE == "AdaMatch":
                launch_job(cfg=cfg, init_method=args.init_method, func=adamatch)
            elif cfg.ADAPTATION.ADAPTATION_TYPE == "MME":
                launch_job(cfg=cfg, init_method=args.init_method, func=mme)
            elif cfg.ADAPTATION.ADAPTATION_TYPE == "MCD":
                launch_job(cfg=cfg, init_method=args.init_method, func=mcd)
            else:
                raise NotImplementedError
        else:
            launch_job(cfg=cfg, init_method=args.init_method, func=train)

    # Perform multi-clip testing.
    if cfg.TEST.ENABLE:
        launch_job(cfg=cfg, init_method=args.init_method, func=test)

    # Perform feature extraction.
    if cfg.EXTRACT.ENABLE:
        launch_job(cfg=cfg, init_method=args.init_method, func=extract)

    # Perform model visualization.
    if cfg.TENSORBOARD.ENABLE and (
        cfg.TENSORBOARD.MODEL_VIS.ENABLE
        or cfg.TENSORBOARD.WRONG_PRED_VIS.ENABLE
    ):
        launch_job(cfg=cfg, init_method=args.init_method, func=visualize)

if __name__ == "__main__":
    main()
