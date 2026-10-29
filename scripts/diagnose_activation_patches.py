"""只在固定开发消息上核验真实 Patch 对照；不充当 held-out 防御比较。"""

import argparse
from pathlib import Path

from warden.infrastructure.adapters.stego_patch_diagnostic import diagnose

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    diagnose(args.config, args.destination)
