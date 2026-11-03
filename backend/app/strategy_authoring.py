"""Bounded authoring rules, deterministic source generation and non-proof checks."""
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.python_strategy import compile_program, generate_python_targets
from app.zk_python import LIMIT, UnsupportedStrategy


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Operand(RuleModel):
    kind: Literal["close", "sma", "index", "constant"]
    value: int = Field(ge=0, le=LIMIT, strict=True)

    @model_validator(mode="after")
    def valid_argument(self):
        if self.kind == "sma" and not 1 <= self.value <= 500:
            raise ValueError("sma周期必须在1至500之间")
        if self.kind == "close" and self.value > 500:
            raise ValueError("close滞后必须在0至500之间")
        if self.kind == "index" and self.value != 0:
            raise ValueError("index不接受参数，value应为0")
        return self

    def source(self):
        if self.kind == "constant":
            return str(self.value)
        if self.kind == "index":
            return "index"
        return f"{self.kind}({self.value})"


class Condition(RuleModel):
    left: Operand
    operator: Literal[">", ">=", "<", "<=", "==", "!="]
    right: Operand


class PositionRule(RuleModel):
    conditions: list[Condition] = Field(min_length=1, max_length=4)
    target_bps: int = Field(ge=0, le=9500, strict=True)


class StrategyRules(RuleModel):
    warmup: int = Field(ge=1, le=501, strict=True)
    rules: list[PositionRule] = Field(min_length=1, max_length=6)
    default_target_bps: int = Field(ge=0, le=9500, strict=True)


class RuleSuggestion(RuleModel):
    kind: Literal["strategy", "explain", "unsupported"]
    explanation: str = Field(min_length=1, max_length=4000)
    plan: StrategyRules | None = None

    @model_validator(mode="after")
    def plan_matches_kind(self):
        if (self.kind == "strategy") != (self.plan is not None):
            raise ValueError("只有strategy回复必须包含plan；explain/unsupported的plan必须为空")
        return self


def rules_to_source(plan: StrategyRules) -> str:
    """The first matching rule wins. No model text is executed or interpolated."""
    warmup = plan.warmup
    lines = ["def target_bps(index, close, sma):"]
    for number, rule in enumerate(plan.rules, 1):
        lines.append(f"    # 规则{number}：全部条件满足时，目标仓位为{rule.target_bps}bps。")
        condition = "1"
        tests = []
        for position, item in enumerate(rule.conditions, 1):
            for operand in (item.left, item.right):
                if operand.kind in {"sma", "close"}:
                    warmup = max(warmup, operand.value + int(operand.kind == "close"))
            test = f"{item.left.source()} {item.operator} {item.right.source()}"
            name = f"rule_{number}_condition_{position}"
            lines.append(f"    {name} = {test}")
            tests.append(name)
        for test in reversed(tests):
            condition = f"({condition} if {test} else 0)"
        lines.extend([f"    rule_{number}_matches = {condition}", ""])
    lines.extend(["    # 从低优先级向上覆盖，第一条匹配规则优先。",
                  f"    target_bps_value = {plan.default_target_bps}"])
    for number, rule in reversed(list(enumerate(plan.rules, 1))):
        lines.append(f"    target_bps_value = {rule.target_bps} if rule_{number}_matches else target_bps_value")
    lines.extend(["", "    # 行情尚未覆盖所有回看周期时保持空仓。", f"    warmup_bars = {warmup}",
                  "    return target_bps_value if index >= warmup_bars else 0", ""])
    return "\n".join(lines)


def check_bounded_source(source: str) -> dict:
    """Same compiler/interpreter as backtests, on explicit synthetic input only."""
    result = {"valid": False, "error": None, "syntax_valid": False,
              "backtest_compatible": False, "proof_compatible": False,
              "dry_run": None, "instruction_count": None}
    try:
        compile(source, "strategy.py", "exec", dont_inherit=True)
    except (SyntaxError, ValueError, RecursionError) as exc:
        result["error"] = {"message": getattr(exc, "msg", str(exc)),
                           "line": getattr(exc, "lineno", None), "offset": getattr(exc, "offset", None), "kind": "syntax"}
        return result
    result["syntax_valid"] = True
    try:
        program = compile_program(source)
        result.update(backtest_compatible=True, proof_compatible=True, instruction_count=len(program))
        count = 520
        scenarios = ([100 + i for i in range(count)], [620 - i for i in range(count)],
                     [100] * count, [100] * (count - 1) + [10000])
        observed = set()
        for prices in scenarios:
            targets, _ = generate_python_targets(pd.DataFrame({"close": prices}), program)
            observed.update(round(value * 10000) for value in targets)
        result["dry_run"] = {"passed": True, "synthetic": True, "scenarios": len(scenarios),
                             "bars_per_scenario": count, "observed_target_bps": sorted(observed)}
        result["valid"] = True
    except UnsupportedStrategy as exc:
        result["error"] = exc.diagnostic(source)
    except RecursionError:
        result["error"] = {"message": "表达式嵌套过深，请减少嵌套条件", "line": None, "offset": None, "kind": "complexity"}
    return result
