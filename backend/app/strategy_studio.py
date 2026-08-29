from __future__ import annotations

import ast
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import ValidationError

from app.config import DATA_DIR, DB_PATH
from app.quantjudge import canonical_json, json_object, sha256_hex, utc_now
from app.strategy_studio_models import StrategyManifest, StrategyWorkflow

MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_FILES = 200
MAX_MANIFEST_BYTES = 256 * 1024
SAFE_SUFFIXES = {".py", ".json", ".md", ".txt", ".toml", ".lock", ".csv"}
FORBIDDEN_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.json",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer"}
TRUSTED_IMPORT_ROOTS = {
    "atlas_strategy_sdk",
    "collections",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "functools",
    "itertools",
    "math",
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "statistics",
    "typing",
}

STAGE_BY_TYPE = {
    "market_data": 10,
    "universe": 10,
    "feature_engine": 20,
    "strategy": 30,
    "position_sizer": 40,
    "risk_gate": 50,
    "execution_review": 55,
    "execution": 60,
    "audit": 70,
    "output": 80,
}
AI_STAGE_BY_ROLE = {
    "regime_detection": 25,
    "signal_review": 35,
    "position_management": 45,
    "risk_control": 48,
    "execution_review": 55,
}


class StrategyPackageError(ValueError):
    pass


@dataclass
class PackageInspection:
    manifest: StrategyManifest
    content_hash: str
    manifest_hash: str
    file_count: int
    expanded_bytes: int
    warnings: list[str]
    sandbox_required: bool


class EncryptedArtifactStore:
    def __init__(
        self,
        root: Path = DATA_DIR / "quantjudge_packages",
        key_path: Path = DATA_DIR / "quantjudge_package.key",
    ):
        self.root = root
        self.key_path = key_path
        self.root.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = AESGCM.generate_key(bit_length=256)
            key_path.write_bytes(key)
        if len(key) != 32:
            raise RuntimeError("策略包加密密钥长度无效")
        os.chmod(key_path, 0o600)
        self._cipher = AESGCM(key)

    def write(self, artifact_id: str, content: bytes, associated_data: bytes) -> Path:
        encrypted = self.seal(content, associated_data)
        destination = self.root / f"{artifact_id}.qstrategy.enc"
        destination.write_bytes(encrypted)
        os.chmod(destination, 0o600)
        return destination

    def read(self, artifact_id: str, associated_data: bytes) -> bytes:
        path = self.root / f"{artifact_id}.qstrategy.enc"
        encrypted = path.read_bytes()
        return self.open(encrypted, associated_data)

    def seal(self, content: bytes, associated_data: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, content, associated_data)

    def open(self, encrypted: bytes, associated_data: bytes) -> bytes:
        if len(encrypted) < 29:
            raise StrategyPackageError("加密密文已损坏")
        return self._cipher.decrypt(encrypted[:12], encrypted[12:], associated_data)

    def delete(self, artifact_id: str) -> None:
        path = self.root / f"{artifact_id}.qstrategy.enc"
        if path.exists():
            path.unlink()


def _safe_member(info: zipfile.ZipInfo) -> PurePosixPath:
    if "\\" in info.filename or "\x00" in info.filename:
        raise StrategyPackageError("策略包包含非法路径")
    path = PurePosixPath(info.filename)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise StrategyPackageError("策略包包含路径穿越")
    unix_mode = info.external_attr >> 16
    if stat.S_ISLNK(unix_mode):
        raise StrategyPackageError("策略包不允许符号链接")
    return path


def inspect_strategy_package(content: bytes) -> PackageInspection:
    if not content or len(content) > MAX_ARCHIVE_BYTES:
        raise StrategyPackageError("策略包必须介于 1B–10MB")
    try:
        archive = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise StrategyPackageError("文件不是有效的 .qstrategy/ZIP 包") from exc
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if not infos or len(infos) > MAX_FILES:
        raise StrategyPackageError(f"策略包文件数必须介于 1–{MAX_FILES}")
    expanded = sum(info.file_size for info in infos)
    compressed = sum(max(info.compress_size, 1) for info in infos)
    if expanded > MAX_EXPANDED_BYTES or expanded / compressed > 100:
        raise StrategyPackageError("策略包触发解压大小或压缩比限制")
    members: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        path = _safe_member(info)
        normalized = path.as_posix()
        if normalized in members:
            raise StrategyPackageError(f"策略包包含重复路径: {normalized}")
        if path.name.lower() in FORBIDDEN_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
            raise StrategyPackageError(f"策略包不得包含密钥或凭证文件: {normalized}")
        if path.suffix.lower() not in SAFE_SUFFIXES:
            raise StrategyPackageError(f"不支持的策略包文件类型: {normalized}")
        members[normalized] = info
    manifest_info = members.get("strategy.json")
    if manifest_info is None or manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise StrategyPackageError("策略包根目录必须包含不超过 256KB 的 strategy.json")
    try:
        manifest_payload = json.loads(archive.read(manifest_info))
        manifest = StrategyManifest.model_validate(manifest_payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise StrategyPackageError(f"strategy.json 校验失败: {exc}") from exc

    warnings: list[str] = []
    sandbox_required = manifest.language == "python"
    if manifest.language == "python":
        entry_file, class_name = manifest.entrypoint.split(":", 1)  # type: ignore[union-attr]
        entry_info = members.get(PurePosixPath(entry_file).as_posix())
        if entry_info is None:
            raise StrategyPackageError(f"Python 入口文件不存在: {entry_file}")
        entry_class_found = False
        for name, info in members.items():
            if not name.endswith(".py"):
                continue
            try:
                source = archive.read(info).decode("utf-8")
                tree = ast.parse(source, filename=name)
            except (UnicodeDecodeError, SyntaxError) as exc:
                raise StrategyPackageError(f"Python 语法校验失败 {name}: {exc}") from exc
            if name == PurePosixPath(entry_file).as_posix():
                entry_class_found = any(
                    isinstance(node, ast.ClassDef) and node.name == class_name for node in tree.body
                )
            imports = {
                node.names[0].name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import) and node.names
            }
            imports.update(
                node.module.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            )
            untrusted = sorted(imports.difference(TRUSTED_IMPORT_ROOTS))
            if untrusted:
                warnings.append(
                    f"{name} 引用非默认依赖: {', '.join(untrusted)}；需在隔离 Runner 中审批"
                )
        if not entry_class_found:
            raise StrategyPackageError(f"入口类不存在: {manifest.entrypoint}")
    elif manifest.language == "json_dsl" and "rules.json" not in members:
        raise StrategyPackageError("JSON DSL 包必须包含 rules.json")
    elif manifest.language == "remote_runner" and "runner-contract.json" not in members:
        raise StrategyPackageError("远程 Runner 包必须包含 runner-contract.json")

    if len(manifest.parameters) > 12:
        warnings.append("参数超过 12 个；请论证每个自由度并防止过拟合")
    if not manifest.research.walk_forward_required:
        warnings.append("未要求 Walk-forward；策略不应进入实盘等级")
    return PackageInspection(
        manifest=manifest,
        content_hash=hashlib.sha256(content).hexdigest(),
        manifest_hash=sha256_hex(canonical_json(manifest.model_dump(mode="json"))),
        file_count=len(infos),
        expanded_bytes=expanded,
        warnings=warnings,
        sandbox_required=sandbox_required,
    )


def _node_stage(node: dict[str, Any]) -> int:
    if node["type"] == "ai_guard":
        return AI_STAGE_BY_ROLE[node["config"]["role"]]
    return STAGE_BY_TYPE[node["type"]]


def validate_workflow(workflow: StrategyWorkflow) -> dict[str, Any]:
    nodes = {node.id: node.model_dump(mode="json") for node in workflow.nodes}
    errors: list[str] = []
    warnings: list[str] = []
    if len(nodes) != len(workflow.nodes):
        errors.append("节点 ID 不能重复")
    required_types = {"market_data", "strategy", "risk_gate", "execution", "audit", "output"}
    present_types = {node["type"] for node in nodes.values() if node["enabled"]}
    missing = required_types.difference(present_types)
    if missing:
        errors.append(f"工作流缺少必需节点: {', '.join(sorted(missing))}")

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}
    seen_edges: set[tuple[str, str]] = set()
    for edge in workflow.edges:
        if edge.source not in nodes or edge.target not in nodes:
            errors.append(f"连线引用不存在节点: {edge.source} -> {edge.target}")
            continue
        pair = (edge.source, edge.target)
        if pair in seen_edges:
            errors.append(f"重复连线: {edge.source} -> {edge.target}")
            continue
        seen_edges.add(pair)
        if not nodes[edge.source]["enabled"] or not nodes[edge.target]["enabled"]:
            errors.append(f"禁用节点不能保留连线: {edge.source} -> {edge.target}")
        if _node_stage(nodes[edge.source]) > _node_stage(nodes[edge.target]):
            errors.append(f"节点顺序非法: {edge.source} 不能流向 {edge.target}")
        adjacency[edge.source].append(edge.target)
        indegree[edge.target] += 1

    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited: list[str] = []
    while queue:
        node_id = queue.pop(0)
        visited.append(node_id)
        for target in adjacency[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(visited) != len(nodes):
        errors.append("工作流必须是无环 DAG")

    executions = [node_id for node_id, node in nodes.items() if node["type"] == "execution"]
    decision_nodes = [
        node_id
        for node_id, node in nodes.items()
        if node["type"] in {"strategy", "position_sizer", "ai_guard"}
    ]
    risk_nodes = {node_id for node_id, node in nodes.items() if node["type"] == "risk_gate"}

    def path_without_risk(start: str, target: str) -> bool:
        stack = [start]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen or current in risk_nodes:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, []))
        return False

    for execution in executions:
        bypasses = [node_id for node_id in decision_nodes if path_without_risk(node_id, execution)]
        if bypasses:
            errors.append(
                f"硬风控被绕过: {', '.join(bypasses)} 可不经 risk_gate 到达 {execution}"
            )

    def reaches_type(start: str, target_type: str) -> bool:
        stack = [start]
        seen: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if nodes[current]["type"] == target_type:
                return True
            stack.extend(adjacency.get(current, []))
        return False

    for execution in executions:
        if not reaches_type(execution, "audit"):
            errors.append(f"执行节点 {execution} 必须到达 audit 审计节点")
        if not reaches_type(execution, "output"):
            errors.append(f"执行节点 {execution} 必须到达 output 输出节点")
    for node_id, node in nodes.items():
        if node["type"] == "output" and adjacency.get(node_id):
            errors.append(f"输出节点 {node_id} 必须是终点")

    ai_nodes = [node for node in nodes.values() if node["type"] == "ai_guard"]
    if not ai_nodes:
        warnings.append("当前工作流未启用 AI 节点")
    if len(ai_nodes) > 4:
        warnings.append("AI 节点超过 4 个；请评估延迟、成本与相互冲突")
    for node in ai_nodes:
        if node["config"].get("authority") == "advisory":
            warnings.append(f"{node['label']} 仅提供建议，Runner 不应将其输出直接转为交易")

    topological_order = visited if not errors else []
    graph_hash = sha256_hex(canonical_json(workflow.model_dump(mode="json")))
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "graph_hash": graph_hash,
        "topological_order": topological_order,
        "summary": {
            "nodes": len(nodes),
            "edges": len(workflow.edges),
            "ai_nodes": len(ai_nodes),
            "hard_risk_gates": len(risk_nodes),
        },
    }


class StrategyStudioStore:
    def __init__(
        self,
        path: Path = DB_PATH,
        artifact_store: EncryptedArtifactStore | None = None,
    ):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts = artifact_store or EncryptedArtifactStore(
            self.path.parent / "quantjudge_packages",
            self.path.parent / "quantjudge_package.key",
        )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS qj_strategy_packages (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL REFERENCES qj_agents(id) ON DELETE CASCADE,
                    strategy_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    language TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    file_count INTEGER NOT NULL,
                    expanded_bytes INTEGER NOT NULL,
                    warnings_json TEXT NOT NULL,
                    sandbox_required INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(agent_id, strategy_key, version)
                );
                CREATE TABLE IF NOT EXISTS qj_workflows (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL REFERENCES qj_agents(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    graph_hash TEXT NOT NULL,
                    encrypted_graph BLOB NOT NULL,
                    validation_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(agent_id, id)
                );
                CREATE TABLE IF NOT EXISTS qj_workflow_revisions (
                    workflow_id TEXT NOT NULL REFERENCES qj_workflows(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL,
                    graph_hash TEXT NOT NULL,
                    encrypted_graph BLOB NOT NULL,
                    change_note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(workflow_id, revision)
                );
                """
            )

    def _assert_token(self, agent_id: str, token: str | None) -> None:
        if not token:
            raise PermissionError("缺少开发者凭证")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT developer_token_hash, is_demo FROM qj_agents WHERE id = ?", (agent_id,)
            ).fetchone()
        if row is None:
            raise KeyError(agent_id)
        if row["is_demo"]:
            raise PermissionError("演示 Agent 为只读样本")
        if not secrets.compare_digest(row["developer_token_hash"], sha256_hex(token)):
            raise PermissionError("开发者凭证无效")

    @staticmethod
    def _package_public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "strategy_key": row["strategy_key"],
            "name": row["name"],
            "version": row["version"],
            "language": row["language"],
            "manifest": json_object(row["manifest_json"]),
            "manifest_hash": row["manifest_hash"],
            "content_hash": row["content_hash"],
            "file_count": row["file_count"],
            "expanded_bytes": row["expanded_bytes"],
            "warnings": json.loads(row["warnings_json"]),
            "sandbox_required": bool(row["sandbox_required"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "source_private": True,
            "encrypted_at_rest": True,
        }

    def upload_package(self, agent_id: str, filename: str, content: bytes, token: str | None) -> dict[str, Any]:
        self._assert_token(agent_id, token)
        if not filename.lower().endswith((".qstrategy", ".zip")):
            raise StrategyPackageError("只支持 .qstrategy 或 .zip")
        inspection = inspect_strategy_package(content)
        package_id = f"qsp_{uuid4().hex[:18]}"
        created_at = utc_now().isoformat()
        associated_data = f"{agent_id}:{package_id}:{inspection.content_hash}".encode()
        self.artifacts.write(package_id, content, associated_data)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO qj_strategy_packages (
                        id, agent_id, strategy_key, name, version, language, manifest_json,
                        manifest_hash, content_hash, file_count, expanded_bytes, warnings_json,
                        sandbox_required, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'validated', ?)
                    """,
                    (
                        package_id,
                        agent_id,
                        inspection.manifest.id,
                        inspection.manifest.name,
                        inspection.manifest.version,
                        inspection.manifest.language,
                        canonical_json(inspection.manifest.model_dump(mode="json")),
                        inspection.manifest_hash,
                        inspection.content_hash,
                        inspection.file_count,
                        inspection.expanded_bytes,
                        canonical_json(inspection.warnings),
                        int(inspection.sandbox_required),
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            self.artifacts.delete(package_id)
            raise StrategyPackageError("同一 Agent 下该策略版本已存在") from exc
        return self.get_package(agent_id, package_id, token)

    def list_packages(self, agent_id: str, token: str | None) -> list[dict[str, Any]]:
        self._assert_token(agent_id, token)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM qj_strategy_packages WHERE agent_id = ? ORDER BY created_at DESC",
                (agent_id,),
            ).fetchall()
        return [self._package_public(row) for row in rows]

    def get_package(self, agent_id: str, package_id: str, token: str | None) -> dict[str, Any]:
        self._assert_token(agent_id, token)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM qj_strategy_packages WHERE id = ? AND agent_id = ?",
                (package_id, agent_id),
            ).fetchone()
        if row is None:
            raise KeyError(package_id)
        return self._package_public(row)

    def download_package(self, agent_id: str, package_id: str, token: str | None) -> bytes:
        self._assert_token(agent_id, token)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM qj_strategy_packages WHERE id = ? AND agent_id = ?",
                (package_id, agent_id),
            ).fetchone()
        if row is None:
            raise KeyError(package_id)
        associated_data = f"{agent_id}:{package_id}:{row['content_hash']}".encode()
        return self.artifacts.read(package_id, associated_data)

    def save_workflow(
        self,
        agent_id: str,
        workflow: StrategyWorkflow,
        change_note: str,
        token: str | None,
    ) -> dict[str, Any]:
        self._assert_token(agent_id, token)
        if workflow.package_id:
            with self._connect() as connection:
                package = connection.execute(
                    "SELECT id FROM qj_strategy_packages WHERE id = ? AND agent_id = ?",
                    (workflow.package_id, agent_id),
                ).fetchone()
            if package is None:
                raise StrategyPackageError("工作流引用的私密策略包不存在或不属于该 Agent")
        validation = validate_workflow(workflow)
        graph_json = canonical_json(workflow.model_dump(mode="json"))
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision, created_at FROM qj_workflows WHERE id = ? AND agent_id = ?",
                (workflow.id, agent_id),
            ).fetchone()
            revision = (current["revision"] + 1) if current else 1
            associated_data = f"workflow:{agent_id}:{workflow.id}:{revision}".encode()
            encrypted = self.artifacts.seal(graph_json.encode(), associated_data)
            if current:
                connection.execute(
                    """UPDATE qj_workflows SET name = ?, revision = ?, graph_hash = ?, encrypted_graph = ?,
                       validation_json = ?, status = ?, updated_at = ? WHERE id = ? AND agent_id = ?""",
                    (
                        workflow.name,
                        revision,
                        validation["graph_hash"],
                        encrypted,
                        canonical_json(validation),
                        "validated" if validation["valid"] else "invalid",
                        now,
                        workflow.id,
                        agent_id,
                    ),
                )
            else:
                connection.execute(
                    """INSERT INTO qj_workflows (
                        id, agent_id, name, revision, graph_hash, encrypted_graph,
                        validation_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        workflow.id,
                        agent_id,
                        workflow.name,
                        revision,
                        validation["graph_hash"],
                        encrypted,
                        canonical_json(validation),
                        "validated" if validation["valid"] else "invalid",
                        now,
                        now,
                    ),
                )
            connection.execute(
                """INSERT INTO qj_workflow_revisions (
                    workflow_id, revision, graph_hash, encrypted_graph, change_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (workflow.id, revision, validation["graph_hash"], encrypted, change_note, now),
            )
        return self.get_workflow(agent_id, workflow.id, token)

    def _decrypt_workflow(self, row: sqlite3.Row) -> dict[str, Any]:
        encrypted = row["encrypted_graph"]
        associated_data = f"workflow:{row['agent_id']}:{row['id']}:{row['revision']}".encode()
        plain = self.artifacts.open(encrypted, associated_data)
        return json.loads(plain)

    def get_workflow(self, agent_id: str, workflow_id: str, token: str | None) -> dict[str, Any]:
        self._assert_token(agent_id, token)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM qj_workflows WHERE id = ? AND agent_id = ?", (workflow_id, agent_id)
            ).fetchone()
        if row is None:
            raise KeyError(workflow_id)
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "name": row["name"],
            "revision": row["revision"],
            "graph_hash": row["graph_hash"],
            "workflow": self._decrypt_workflow(row),
            "validation": json_object(row["validation_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "encrypted_at_rest": True,
        }

    def list_workflows(self, agent_id: str, token: str | None) -> list[dict[str, Any]]:
        self._assert_token(agent_id, token)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM qj_workflows WHERE agent_id = ? ORDER BY updated_at DESC", (agent_id,)
            ).fetchall()
        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "name": row["name"],
                "revision": row["revision"],
                "graph_hash": row["graph_hash"],
                "validation": json_object(row["validation_json"]),
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]


def studio_spec() -> dict[str, Any]:
    return {
        "native_format": ".qstrategy",
        "archive": "ZIP",
        "required_files": ["strategy.json"],
        "languages": [
            {"id": "python", "label": "Python SDK", "production": True, "execution": "isolated_runner"},
            {"id": "json_dsl", "label": "JSON 规则 DSL", "production": True, "execution": "safe_interpreter"},
            {"id": "remote_runner", "label": "私有黑盒 Runner", "production": True, "execution": "signed_http_contract"},
            {"id": "pine", "label": "Pine Script", "production": False, "execution": "import_converter"},
            {"id": "notebook", "label": "Jupyter Notebook", "production": False, "execution": "research_attachment"},
        ],
        "limits": {
            "archive_bytes": MAX_ARCHIVE_BYTES,
            "expanded_bytes": MAX_EXPANDED_BYTES,
            "files": MAX_FILES,
        },
        "ai_roles": [
            {"id": "regime_detection", "label": "市场状态识别", "allowed_authority": ["advisory", "veto"]},
            {"id": "signal_review", "label": "信号复核", "allowed_authority": ["advisory", "veto", "bounded_adjustment"]},
            {"id": "position_management", "label": "仓位管理", "allowed_authority": ["advisory", "bounded_adjustment"]},
            {"id": "risk_control", "label": "风险控制", "allowed_authority": ["advisory", "veto", "bounded_adjustment"]},
            {"id": "execution_review", "label": "执行前审查", "allowed_authority": ["advisory", "veto"]},
        ],
        "security": {
            "api_process_executes_user_code": False,
            "encrypted_at_rest": True,
            "python_requires_isolated_runner": True,
            "ai_can_bypass_hard_risk": False,
            "provider_secrets_allowed_in_workflow": False,
        },
    }


def workflow_templates() -> list[dict[str, Any]]:
    base_nodes = [
        {"id": "market", "type": "market_data", "label": "行情与企业行为", "config": {"adjustment": "auto"}},
        {"id": "features", "type": "feature_engine", "label": "特征与因子", "config": {"causal_only": True}},
        {"id": "strategy", "type": "strategy", "label": "策略核心", "config": {"next_bar_execution": True}},
        {"id": "sizer", "type": "position_sizer", "label": "基准仓位", "config": {"method": "volatility_target"}},
        {
            "id": "hard_risk",
            "type": "risk_gate",
            "label": "确定性硬风控",
            "config": {
                "max_gross_exposure": 0.95,
                "max_single_position": 0.2,
                "max_daily_loss": 0.03,
                "max_drawdown": 0.15,
                "max_participation_rate": 0.01,
            },
        },
        {"id": "execution", "type": "execution", "label": "成本与执行", "config": {"commission": 0.001, "slippage": 0.0005}},
        {"id": "audit", "type": "audit", "label": "承诺与审计", "config": {"decision_commitment": True}},
        {"id": "output", "type": "output", "label": "回执与跑分", "config": {}},
    ]
    base_edges = [
        {"source": "market", "target": "features"},
        {"source": "features", "target": "strategy"},
        {"source": "strategy", "target": "sizer"},
        {"source": "sizer", "target": "hard_risk"},
        {"source": "hard_risk", "target": "execution"},
        {"source": "execution", "target": "audit"},
        {"source": "audit", "target": "output"},
    ]
    ai_risk = {
        "id": "ai_risk",
        "type": "ai_guard",
        "label": "AI 风险官",
        "config": {
            "role": "risk_control",
            "authority": "veto",
            "provider_ref": "server:primary-risk-model",
            "timeout_ms": 2500,
            "on_error": "deny",
            "instructions": "识别极端行情、相关性塌缩与流动性风险；只返回结构化风险决策。",
        },
    }
    return [
        {
            "id": "professional_baseline",
            "name": "专业基线树干",
            "description": "因果特征、下一根 K 线执行、硬风控、成本和审计默认齐全。",
            "workflow": {"schema_version": "1.0", "id": "professional_baseline", "name": "专业基线树干", "nodes": base_nodes, "edges": base_edges},
        },
        {
            "id": "ai_risk_governor",
            "name": "AI 风险官树干",
            "description": "AI 拥有否决权，但无法越过其后的确定性硬风控。",
            "workflow": {
                "schema_version": "1.0",
                "id": "ai_risk_governor",
                "name": "AI 风险官树干",
                "nodes": base_nodes + [ai_risk],
                "edges": [
                    edge for edge in base_edges if edge != {"source": "sizer", "target": "hard_risk"}
                ]
                + [
                    {"source": "sizer", "target": "ai_risk"},
                    {"source": "ai_risk", "target": "hard_risk"},
                ],
            },
        },
    ]
