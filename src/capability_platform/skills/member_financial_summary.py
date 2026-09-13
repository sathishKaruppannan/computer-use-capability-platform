from typing import Any, Protocol


class CapabilityInvoker(Protocol):
    async def invoke(self, capability_id: str, inputs: dict[str, Any]) -> dict[str, Any]: ...


class MemberFinancialSummarySkill:
    """Example composable skill; capabilities are injected and remain independently governed."""

    id = "member-financial-summary"
    requires = ("lookup-member-savings-balance.v1",)

    def __init__(self, invoker: CapabilityInvoker) -> None:
        self.invoker = invoker

    async def execute(self, member_id: str) -> dict[str, Any]:
        savings = await self.invoker.invoke(self.requires[0], {"memberId": member_id})
        return {"memberId": member_id, "savings": savings.get("outputs", {})}
