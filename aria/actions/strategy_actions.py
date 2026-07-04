"""Strategy analysis actions."""

from __future__ import annotations

from aria.actions._helpers import json_result
from aria.registry import ActionContext, ActionResult, registry
from aria.strategy_catalog import (
    explain_strategy,
    get_strategy_failure_analysis,
    get_strategy_incubation_status,
    get_strategy_parameters,
    get_strategy_recent_performance,
    get_strategy_validation_status,
)


def _register_strategy_actions() -> None:
    r = registry
    strat_prop = {"strategy": {"type": "string"}}
    r.register_action(
        "get_strategy_performance", "Strategy performance stats.", _performance,
        category="strategy", properties={"strategy_name": {"type": "string"}},
    )
    r.register_action("explain_strategy", "Explain how a WickSense strategy works.", _explain, category="strategy", properties=strat_prop, required=["strategy"])
    r.register_action("get_strategy_parameters", "Show strategy parameters.", _parameters, category="strategy", properties=strat_prop, required=["strategy"])
    r.register_action("get_strategy_recent_performance", "Recent performance for a strategy.", _recent, category="strategy", properties=strat_prop, required=["strategy"])
    r.register_action("get_strategy_validation_status", "Validation status for a strategy.", _validation, category="strategy", properties=strat_prop, required=["strategy"])
    r.register_action("get_strategy_incubation_status", "Incubation/testing status.", _incubation, category="strategy", properties=strat_prop, required=["strategy"])
    r.register_action("get_strategy_failure_analysis", "Failure analysis for a strategy.", _failure, category="strategy", properties=strat_prop, required=["strategy"])


def _performance(ctx: ActionContext) -> ActionResult:
    stats = ctx.state.get("strategyStats") or {}
    filt = (ctx.arguments.get("strategy_name") or "").lower()
    if filt:
        matched = {k: v for k, v in stats.items() if filt in k.lower()}
        return ActionResult(result=json_result(matched or stats))
    return ActionResult(result=json_result(stats))


def _explain(ctx: ActionContext) -> ActionResult:
    return ActionResult(result=explain_strategy(ctx.arguments.get("strategy") or ""))


def _parameters(ctx: ActionContext) -> ActionResult:
    return ActionResult(result=get_strategy_parameters(ctx.arguments.get("strategy") or "", ctx.state))


def _recent(ctx: ActionContext) -> ActionResult:
    return ActionResult(result=get_strategy_recent_performance(ctx.arguments.get("strategy") or "", ctx.state))


def _validation(ctx: ActionContext) -> ActionResult:
    return ActionResult(result=get_strategy_validation_status(ctx.arguments.get("strategy") or "", ctx.state))


def _incubation(ctx: ActionContext) -> ActionResult:
    return ActionResult(result=get_strategy_incubation_status(ctx.arguments.get("strategy") or "", ctx.state))


def _failure(ctx: ActionContext) -> ActionResult:
    return ActionResult(result=get_strategy_failure_analysis(ctx.arguments.get("strategy") or "", ctx.state))


_register_strategy_actions()
