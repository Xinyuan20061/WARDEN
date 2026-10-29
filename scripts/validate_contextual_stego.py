"""只使用 validation 家族核验上下文协议，禁止读取 test 结果选择参数。"""

import argparse
from pathlib import Path

from warden.infrastructure.adapters.stego_validation_diagnostic import validate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    validate(args.config, args.destination)
