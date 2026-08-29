import json
import zipfile
from io import BytesIO

import pytest
from pydantic import ValidationError

from app.quantjudge import sha256_hex
from app.quantjudge_models import QuantAgentCreate
from app.strategy_studio import (
    EncryptedArtifactStore,
    StrategyPackageError,
    StrategyStudioStore,
    inspect_strategy_package,
    validate_workflow,
    workflow_templates,
)
from app.strategy_studio_models import StrategyWorkflow, WorkflowNode
from tests.test_quantjudge import make_store


def package_bytes(extra_files: dict[str, str] | None = None, manifest_updates: dict | None = None) -> bytes:
    manifest = {
        "schema_version": "1.0",
        "api_version": "atlas.strategy/v1",
        "id": "private_momentum",
        "name": "Private Momentum",
        "version": "1.0.0",
        "language": "python",
        "entrypoint": "strategy.py:PrivateMomentum",
        "description": "A causal momentum strategy with volatility-aware position sizing.",
        "asset_classes": ["crypto", "equity"],
        "intervals": ["1h", "1d"],
        "capabilities": ["market_data.read", "signals.write", "ai.request"],
        "parameters": [
            {"key": "lookback", "label": "Lookback", "kind": "integer", "default": 20, "minimum": 2, "maximum": 200}
        ],
        "ai_injection_points": ["risk_control"],
    }
    manifest.update(manifest_updates or {})
    files = {
        "strategy.json": json.dumps(manifest),
        "strategy.py": "from atlas_strategy_sdk import BaseStrategy\nclass PrivateMomentum(BaseStrategy):\n    pass\n",
        "README.md": "Private source documentation",
        **(extra_files or {}),
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return output.getvalue()


def create_private_agent(tmp_path):
    quant_store = make_store(tmp_path)
    created = quant_store.create_agent(
        QuantAgentCreate(
            name="Studio Agent",
            developer_alias="Cipher Studio",
            category="allocation",
            asset_classes=["crypto", "equity"],
            description="A private strategy assembled with the professional strategy studio.",
            strategy_commitment=sha256_hex("private studio strategy"),
        )
    )
    artifacts = EncryptedArtifactStore(tmp_path / "artifacts", tmp_path / "package.key")
    return StrategyStudioStore(tmp_path / "quantjudge.sqlite3", artifacts), created


def test_package_is_validated_encrypted_and_downloadable(tmp_path):
    studio, created = create_private_agent(tmp_path)
    content = package_bytes()
    agent_id = created["agent"]["id"]
    token = created["developer_token"]

    package = studio.upload_package(agent_id, "momentum.qstrategy", content, token)
    ciphertext = (tmp_path / "artifacts" / f"{package['id']}.qstrategy.enc").read_bytes()

    assert package["manifest"]["id"] == "private_momentum"
    assert package["source_private"] is True
    assert b"PrivateMomentum" not in ciphertext
    assert studio.download_package(agent_id, package["id"], token) == content
    assert (tmp_path / "package.key").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("extra_files", "message"),
    [
        ({"../escape.py": "pass"}, "\u8def\u5f84\u7a7f\u8d8a"),
        ({"credentials.json": "{}"}, "\u51ed\u8bc1"),
        ({"model.pkl": "unsafe"}, "\u6587\u4ef6\u7c7b\u578b"),
    ],
)
def test_package_rejects_unsafe_members(extra_files, message):
    with pytest.raises(StrategyPackageError, match=message):
        inspect_strategy_package(package_bytes(extra_files))


def test_package_rejects_missing_python_entry_class():
    with pytest.raises(StrategyPackageError, match="\u5165\u53e3\u7c7b"):
        inspect_strategy_package(package_bytes({"strategy.py": "class SomethingElse:\n    pass\n"}))


def test_workflow_templates_and_ai_permission_model():
    for template in workflow_templates():
        result = validate_workflow(StrategyWorkflow.model_validate(template["workflow"]))
        assert result["valid"] is True
        assert result["summary"]["hard_risk_gates"] == 1

    with pytest.raises(ValidationError, match="\u4e0d\u5141\u8bb8使用"):
        WorkflowNode.model_validate(
            {
                "id": "ai_execution",
                "type": "ai_guard",
                "label": "AI Execution",
                "config": {
                    "role": "execution_review",
                    "authority": "bounded_adjustment",
                    "provider_ref": "server:execution-review",
                    "timeout_ms": 1000,
                    "on_error": "deny",
                    "max_adjustment_bps": 50,
                },
            }
        )

    with pytest.raises(ValidationError, match="密钥或令牌"):
        WorkflowNode.model_validate(
            {
                "id": "ai_risk",
                "type": "ai_guard",
                "label": "AI Risk",
                "config": {
                    "role": "risk_control",
                    "authority": "veto",
                    "provider_ref": "vault:risk-provider",
                    "timeout_ms": 1000,
                    "on_error": "deny",
                    "provider": {"api_key": "must-not-live-in-a-workflow"},
                },
            }
        )


def test_workflow_rejects_hard_risk_bypass():
    payload = workflow_templates()[0]["workflow"]
    payload = json.loads(json.dumps(payload))
    payload["edges"].append({"source": "strategy", "target": "execution"})
    result = validate_workflow(StrategyWorkflow.model_validate(payload))
    assert result["valid"] is False
    assert any("\u786c\u98ce\u63a7被绕过" in error for error in result["errors"])


def test_workflow_revisions_are_encrypted_at_rest(tmp_path):
    studio, created = create_private_agent(tmp_path)
    workflow = StrategyWorkflow.model_validate(workflow_templates()[1]["workflow"])
    token = created["developer_token"]
    agent_id = created["agent"]["id"]

    first = studio.save_workflow(agent_id, workflow, "Initial private AI policy", token)
    workflow.nodes[-1].config["private_instruction"] = "never expose this position policy"
    second = studio.save_workflow(agent_id, workflow, "Tighten model policy", token)

    with studio._connect() as connection:
        current = connection.execute("SELECT encrypted_graph FROM qj_workflows WHERE id = ?", (workflow.id,)).fetchone()[0]
        revisions = connection.execute("SELECT COUNT(*) FROM qj_workflow_revisions WHERE workflow_id = ?", (workflow.id,)).fetchone()[0]
    assert first["revision"] == 1
    assert second["revision"] == 2
    assert revisions == 2
    assert b"never expose" not in current
    assert studio.get_workflow(agent_id, workflow.id, token)["workflow"]["nodes"][-1]["config"]["private_instruction"] == "never expose this position policy"


def test_workflow_cannot_bind_another_or_missing_package(tmp_path):
    studio, created = create_private_agent(tmp_path)
    workflow = StrategyWorkflow.model_validate(workflow_templates()[0]["workflow"])
    workflow.package_id = "qsp_not_owned_or_missing"
    with pytest.raises(StrategyPackageError, match="不存在或不属于"):
        studio.save_workflow(
            created["agent"]["id"], workflow, "invalid binding", created["developer_token"]
        )
