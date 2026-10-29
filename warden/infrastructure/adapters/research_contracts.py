"""把已验证 M 轨道数据注册为独立威胁契约，保留历史来源。"""

from warden.core.domain.models import ThreatContract


class ResearchContractSource:
    """部署者注入的协议契约目录；不读取客户端路径或执行客户端代码。

    参数：contracts 为已验证的契约映射，fallback 为可选历史来源，均不转移资源所有权。
    """

    def __init__(self, contracts, fallback=None):
        self._contracts = dict(contracts)
        self._fallback = fallback

    def list_contracts(self):
        """合并研究契约与原来源，不删除已有公开契约。"""
        original = self._fallback.list_contracts() if self._fallback else ()
        return tuple(sorted(set(original) | self._contracts.keys()))

    def load(self, contract_id: str) -> ThreatContract:
        """加载可信契约；未知标识明确报错。"""
        if contract_id in self._contracts:
            return self._contracts[contract_id]
        if self._fallback:
            return self._fallback.load(contract_id)
        raise KeyError(contract_id)
