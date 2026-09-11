"""Authenticated setup of demo-only accounts; verifies balance before saving."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

from app import demo_credentials, trading_api
from app.trading import Exchange, Venue


class DemoConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr
    secret: SecretStr
    passphrase: SecretStr = SecretStr("")
    consent: Literal[True]

    @model_validator(mode="after")
    def valid(self):
        for item in (self.api_key, self.secret):
            text = item.get_secret_value()
            if not 1 <= len(text) <= 512 or any(ch.isspace() for ch in text):
                raise ValueError("模拟密钥不能为空、过长或包含空白")
        phrase = self.passphrase.get_secret_value()
        if len(phrase) > 512 or any(ch.isspace() for ch in phrase):
            raise ValueError("Passphrase格式无效")
        return self


def router(store):
    routes = APIRouter(prefix="/api/v1/trading/demo-accounts", tags=["demo-account-setup"])

    @routes.put("/{venue}")
    def configure(venue: Venue, body: DemoConnection, request: Request):
        user = request.state.user.id
        values = {
            "api_key": body.api_key.get_secret_value(),
            "secret": body.secret.get_secret_value(),
            "passphrase": body.passphrase.get_secret_value(),
        }
        if venue == "okx" and not values["passphrase"]:
            raise HTTPException(422, "欧易模拟账户需要Passphrase")
        candidate = Exchange(venue, owner=user, demo_credentials=values)
        current = Exchange(venue, owner=user)
        if current.configured and candidate.fingerprint() != current.fingerprint():
            with trading_api.database() as connection:
                pending = connection.execute(
                    "SELECT 1 FROM manual_trade_orders WHERE owner=? AND venue=? "
                    "AND state NOT IN ('preview_expired','rejected') "
                    "AND COALESCE(json_extract(result,'$.strategy_sync_complete'),0)<>1",
                    (user, venue),
                ).fetchone()
            with store._connect() as connection:
                active = connection.execute(
                    "SELECT 1 FROM strategy_runs r JOIN strategy_account_bindings b "
                    "ON b.account_id=r.account_id "
                    "WHERE r.owner_id=? AND b.fingerprint=? "
                    "AND (r.status IN ('draft','active','paused') "
                    "OR CAST(r.quantity AS REAL)>0)",
                    (user, current.fingerprint()),
                ).fetchone()
            if pending or active:
                raise HTTPException(
                    409, "原账户仍有运行策略、持仓或待核实订单，请处理完成后再更换密钥"
                )
        try:
            candidate.account()  # No order is sent by setup, and live endpoints are never used.
        except HTTPException:
            raise HTTPException(
                422, "模拟账户验证失败：请核对测试环境密钥、现货查询权限、IP白名单和欧易Passphrase"
            ) from None
        demo_credentials.save(user, venue, values)
        accounts = store.list_accounts(user)
        synced = False
        for account in accounts:
            if account["environment"] == "exchange_test" and account["name"].lower().startswith(
                venue
            ):
                try:
                    store.sync_account(user, account["id"])
                    synced = True
                except HTTPException:
                    continue
        return {
            "configured": True,
            "verified": True,
            "synced": synced,
            "mode": "demo",
            "venue": venue,
            "accounts": [item for item in accounts if item["environment"] == "exchange_test"],
            "message": "模拟账户已验证并保存，可选择账户启动策略；未提交订单",
        }

    return routes
