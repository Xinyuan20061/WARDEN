"""WARDEN 命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from warden import __version__
from warden.core.domain.models import to_primitive
from warden.interface.factory import build_default_service


def build_parser() -> argparse.ArgumentParser:
    """创建不执行副作用的 CLI 参数解析器。"""

    parser = argparse.ArgumentParser(
        prog="warden",
        description="WARDEN 因果审计与可控防御内核",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="检查依赖、Adapter 和训练资源状态")
    resources = commands.add_parser("resources", help="列出 Probe 与 SAE 资源清单")
    resources.add_argument("--kind", choices=("probe", "sae"))
    commands.add_parser("contracts", help="列出当前 FRACTAL-Bench 契约")
    serve = commands.add_parser("serve", help="启动供测试平台调用的 REST API")
    serve.add_argument("--host", default=os.getenv("WARDEN_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.getenv("WARDEN_PORT", "8765")))
    whitebox_preflight = commands.add_parser(
        "whitebox-preflight",
        help="不加载模型地检查白盒 Probe 实验配置",
    )
    whitebox_preflight.add_argument("--config", type=Path, required=True)
    whitebox_run = commands.add_parser(
        "whitebox-run",
        help="采集真实 Activation 并训练多主体 Probe Suite",
    )
    whitebox_run.add_argument("--config", type=Path, required=True)
    whitebox_run.add_argument(
        "--phase",
        choices=("collect", "train", "all"),
        default="all",
        help="collect 使用模型/GPU，train 只消费已有 Corpus，all 顺序执行",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行 CLI 并返回进程退出码。"""

    args = build_parser().parse_args(argv)
    service = build_default_service(_project_root())
    if args.command == "doctor":
        payload = {
            "version": __version__,
            "components": [to_primitive(item) for item in service.capabilities()],
            "resources": [to_primitive(item) for item in service.list_resources()],
            "contracts": list(service.list_contracts()),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "resources":
        values = service.list_resources(kind=args.kind)
        print(json.dumps([to_primitive(item) for item in values], ensure_ascii=False, indent=2))
        return 0
    if args.command == "contracts":
        print(json.dumps(list(service.list_contracts()), ensure_ascii=False, indent=2))
        return 0
    if args.command == "serve":
        try:
            import uvicorn
        except ImportError as exc:
            raise RuntimeError("启动 API 需要安装 warden-kernel[api]") from exc
        from warden.interface.api.app import create_app

        uvicorn.run(create_app(service, research_token=os.getenv("WARDEN_RESEARCH_TOKEN")),
                    host=args.host, port=args.port)
        return 0
    if args.command in {"whitebox-preflight", "whitebox-run"}:
        from warden.infrastructure.workflows import (
            load_whitebox_probe_config,
            preflight_whitebox_probe_experiment,
            run_whitebox_probe_experiment,
        )

        config = load_whitebox_probe_config(args.config)
        if args.command == "whitebox-preflight":
            report = preflight_whitebox_probe_experiment(config)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 2
        summary = run_whitebox_probe_experiment(
            config,
            phase=args.phase,
            progress=lambda message: print(f"[WARDEN] {message}", file=sys.stderr, flush=True),
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    raise AssertionError(f"未处理命令：{args.command}")


def _project_root() -> Path:
    """优先返回源码仓库根目录，安装包环境退化为当前目录。"""

    candidate = Path(__file__).resolve().parents[2]
    return candidate if (candidate / "pyproject.toml").is_file() else Path.cwd()


if __name__ == "__main__":
    raise SystemExit(main())
