"""只运行少量开发诊断；从不读取 held-out 数据，不替代正式模型实验。"""

import argparse
from pathlib import Path

from warden.infrastructure.adapters.stego_behavior_diagnostic import diagnose

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    diagnose(args.config, args.destination)
