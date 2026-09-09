"""Versioned station ownership and immutable per-node review capabilities."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from libs.review_orchestrator.tool_scope import ALWAYS_AVAILABLE_TOOLS

REGISTRY = Path(__file__).resolve().parents[1] / 'config/workstations/registry.json'


class WorkstationConfigurationError(ValueError):
    """A missing or inconsistent station must never become an all-purpose agent."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def node_number(value: Any) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= 69:
        raise WorkstationConfigurationError('invalid_workstation_node')
    return int(value)


def load_registry(path: Path = REGISTRY) -> dict[str, Any]:
    asset = json.loads(path.read_text())
    if asset.get('schemaVersion') != 'workstations-v1' or not asset.get('version'):
        raise WorkstationConfigurationError('invalid_workstation_registry_version')
    seen_nodes: set[int] = set()
    seen_stations: set[str] = set()
    for station in asset.get('stations') or []:
        station_id = station.get('id')
        if station_id not in set('ABCDEFGHI') or station_id in seen_stations:
            raise WorkstationConfigurationError('duplicate_or_unknown_workstation')
        seen_stations.add(station_id)
        if not station.get('nodeIds') or not station.get('promptVersion'):
            raise WorkstationConfigurationError('workstation_nodes_or_prompt_version_missing')
        for value in station['nodeIds']:
            number = node_number(value)
            if number in seen_nodes:
                raise WorkstationConfigurationError('duplicate_node_owner')
            seen_nodes.add(number)
        prompt_path = (path.parent / station['promptFile']).resolve()
        if not prompt_path.is_relative_to(path.parent.resolve()):
            raise WorkstationConfigurationError('prompt_path_outside_registry')
        station['systemPrompt'] = prompt_path.read_text()
        if not station['systemPrompt'].strip():
            raise WorkstationConfigurationError('workstation_prompt_empty')
    if seen_nodes != set(range(1, 70)) or seen_stations != set('ABCDEFGHI'):
        raise WorkstationConfigurationError('incomplete_workstation_coverage')
    return asset


def freeze_station(node_id: Any, pack: dict[str, Any], catalog: list[dict[str, Any]],
                   *, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    asset = registry if registry is not None else load_registry()
    number = node_number(node_id)
    if pack.get('id') != asset['businessPackId']:
        raise WorkstationConfigurationError('workstation_business_pack_mismatch')
    station = next((row for row in asset['stations'] if number in row['nodeIds']), None)
    if station is None:
        raise WorkstationConfigurationError('node_owner_missing')
    rule_ids = {row['sourceRuleId'] for row in pack.get('atomicChecks') or [] if row.get('nodeId') == number}
    bindings = [row for row in pack.get('atomicCheckToolBindings') or [] if row.get('sourceRuleId') in rule_ids]
    checks = {row['id'] for row in pack.get('atomicChecks') or [] if row.get('nodeId') == number}
    if not checks or {row['atomicCheckId'] for row in bindings} != checks:
        raise WorkstationConfigurationError('node_bindings_incomplete')
    available = {row['name'] for row in catalog}
    required = {name for row in bindings for name in row.get('tools') or []}
    if not required or required - available:
        raise WorkstationConfigurationError('node_tools_missing')
    snapshot = {
        'schemaVersion': 'workstation-run-v1', 'stationId': station['id'],
        'stationName': station['name'], 'routeVersion': asset['version'],
        'promptVersion': station['promptVersion'], 'systemPrompt': station['systemPrompt'],
        'businessPackId': asset['businessPackId'], 'targetNodeId': number,
        'ownedNodeIds': list(station['nodeIds']), 'ruleIds': sorted(rule_ids),
        'atomicCheckIds': sorted(checks), 'bindingsHash': digest(bindings),
        'allowedTools': sorted(required | (ALWAYS_AVAILABLE_TOOLS & available)),
    }
    snapshot['snapshotHash'] = digest(snapshot)
    return deepcopy(snapshot)


def station_snapshot(review_run: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = review_run.get('workstationSnapshot')
    if snapshot is None:
        return None  # Historical runs retain their original execution contract.
    if not isinstance(snapshot, dict) or snapshot.get('schemaVersion') != 'workstation-run-v1':
        raise WorkstationConfigurationError('invalid_workstation_snapshot')
    content = {key: value for key, value in snapshot.items() if key != 'snapshotHash'}
    if digest(content) != snapshot.get('snapshotHash'):
        raise WorkstationConfigurationError('workstation_snapshot_hash_mismatch')
    if node_number(review_run.get('nodeId')) != snapshot['targetNodeId'] or snapshot['targetNodeId'] not in snapshot['ownedNodeIds']:
        raise WorkstationConfigurationError('workstation_target_mismatch')
    if review_run.get('businessPackId') != snapshot['businessPackId']:
        raise WorkstationConfigurationError('workstation_snapshot_pack_mismatch')
    return deepcopy(snapshot)


def scope_catalog(review_run: dict[str, Any], catalog: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = station_snapshot(review_run)
    if snapshot is None:
        raise WorkstationConfigurationError('workstation_snapshot_missing')
    names = set(snapshot['allowedTools'])
    if names - {item['name'] for item in catalog}:
        raise WorkstationConfigurationError('frozen_workstation_tools_unavailable')
    return [item for item in catalog if item['name'] in names], {
        'scoped': True, 'reason': 'frozen_workstation_node_capabilities',
        'stationId': snapshot['stationId'], 'snapshotHash': snapshot['snapshotHash'],
        'nodeId': snapshot['targetNodeId'], 'toolCount': len(names),
    }


def tool_allowed(review_run: dict[str, Any], tool_name: str) -> bool:
    snapshot = station_snapshot(review_run)
    return snapshot is None or tool_name in snapshot['allowedTools']


def apply_station_messages(review_run: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace legacy roles; retain node procedure as task data, never a second identity."""
    snapshot = station_snapshot(review_run)
    if snapshot is None:
        return messages
    output = [{'role': 'system', 'content': snapshot['systemPrompt']}]
    for message in messages:
        if message.get('role') == 'system':
            procedure = re.sub(r'^你是.*?Agent[。．]?', '', str(message.get('content') or '')).strip()
            if procedure:
                output.append({'role': 'user', 'content': json.dumps({'targetNodeId': snapshot['targetNodeId'], 'nodeProcedure': procedure}, ensure_ascii=False)})
            continue
        output.append(deepcopy(message))
    return output
