from pathlib import Path

from libs.business_pack import load_business_pack
from scripts.import_offline_test_projects import (
    apply_project_import_plan,
    build_project_import_plan,
    local_storage_key,
    require_postgres_persistence,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def assert_plan_covers_full_corpus(project_code: str, plan) -> None:
    source_root = REPO_ROOT / project_code
    source_files = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }
    assert {item.relative_path for item in plan.files} == source_files
    assert {item.file_id for item in plan.files} == {
        path.stem for path in plan.files[0].ocr_path.parent.glob("*.md")
    }


def test_test_project_plan_contains_every_source_file_and_all_69_nodes() -> None:
    plan = build_project_import_plan(REPO_ROOT, "test")

    assert plan.project_id == "P-TEST-OCR-001"
    assert plan.project_name == "TEST项目一｜珠海海瑞德制药压力管道安装"
    assert len(plan.nodes) == 69
    assert len(plan.files) == 23
    assert len(plan.bindings) == 76
    assert {item.uploader_name for item in plan.files} >= {"李工", "王工"}
    assert all(item.source_path.is_file() for item in plan.files)
    assert all(item.ocr_path.is_file() for item in plan.files)
    assert_plan_covers_full_corpus("test", plan)
    assert next(item for item in plan.files if item.file_id == "test-quality-manual-001").material_type_codes == (
        "quality_system_document",
    )


def test_test2_project_plan_contains_every_source_file_and_all_69_nodes() -> None:
    plan = build_project_import_plan(REPO_ROOT, "test2")

    assert plan.project_id == "P-TEST-OCR-002"
    assert plan.project_name == "TEST项目二｜珠海新建化工区管道气站"
    assert len(plan.nodes) == 69
    assert len(plan.files) == 20
    assert len(plan.bindings) == 68
    assert {item.uploader_name for item in plan.files} >= {"李工", "王工"}
    assert all(item.source_path.is_file() for item in plan.files)
    assert all(item.ocr_path.is_file() for item in plan.files)
    assert_plan_covers_full_corpus("test2", plan)
    assert next(item for item in plan.files if item.file_id == "test2-006").material_type_codes == (
        "quality_system_document",
    )


def test_offline_import_plan_is_stable_for_idempotent_upserts() -> None:
    first = build_project_import_plan(REPO_ROOT, "test")
    second = build_project_import_plan(REPO_ROOT, "test")

    assert [item.document_id for item in first.files] == [
        item.document_id for item in second.files
    ]
    assert [item.binding_id for item in first.bindings] == [
        item.binding_id for item in second.bindings
    ]


def test_applying_the_same_plan_twice_does_not_duplicate_project_data() -> None:
    state: dict[str, list[dict]] = {}
    plan = build_project_import_plan(REPO_ROOT, "test")
    pack = load_business_pack("engineering_inspection_v1")

    first = apply_project_import_plan(state, plan, pack)
    second = apply_project_import_plan(state, plan, pack)

    assert first == second
    assert len(state["projects"]) == 1
    assert len(state["tree_nodes"]) == 69
    assert len(state["documents"]) == 23
    assert len(state["versions"]) == 23
    assert len(state["ocr_parse_results"]) == 23
    assert len(state["bindings"]) == 76
    assert len(state["node_evidence_links"]) == 76
    assert len(state["project_members"]) == 4
    assert {item["uploaderName"] for item in state["documents"]} >= {"李工", "王工"}
    assert all(item["bodyUploaded"] for item in state["documents"])
    assert all(item["id"].startswith("NEL-BIND-OFFLINE-") for item in state["node_evidence_links"])


def test_two_projects_keep_separate_requirements_with_shared_business_ids() -> None:
    state: dict[str, list[dict]] = {}
    pack = load_business_pack("engineering_inspection_v1")

    apply_project_import_plan(state, build_project_import_plan(REPO_ROOT, "test"), pack)
    apply_project_import_plan(state, build_project_import_plan(REPO_ROOT, "test2"), pack)

    requirements_by_project = {
        project_id: [
            item for item in state["requirements"] if item.get("projectId") == project_id
        ]
        for project_id in ("P-TEST-OCR-001", "P-TEST-OCR-002")
    }
    assert len(requirements_by_project["P-TEST-OCR-001"]) == 167
    assert len(requirements_by_project["P-TEST-OCR-002"]) == 167


def test_reimport_removes_stale_records_owned_by_the_offline_scenario() -> None:
    state: dict[str, list[dict]] = {
        "documents": [
            {
                "id": "STALE-DOC",
                "projectId": "P-TEST-OCR-001",
                "scenarioTag": "offline-test-projects-v1",
            }
        ],
        "versions": [
            {
                "id": "STALE-VERSION",
                "documentId": "STALE-DOC",
                "scenarioTag": "offline-test-projects-v1",
            }
        ],
        "node_evidence_links": [
            {
                "id": "STALE-LINK",
                "projectId": "P-TEST-OCR-001",
                "scenarioTag": "offline-test-projects-v1",
            }
        ]
    }

    apply_project_import_plan(
        state,
        build_project_import_plan(REPO_ROOT, "test"),
        load_business_pack("engineering_inspection_v1"),
    )

    assert not any(item["id"] == "STALE-LINK" for item in state["node_evidence_links"])
    assert not any(item["id"] == "STALE-VERSION" for item in state["versions"])


def test_local_storage_key_is_relative_to_any_repository_name(tmp_path: Path) -> None:
    repo_root = tmp_path / "renamed-checkout"
    source = repo_root / "test" / "证书.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"test")

    assert local_storage_key(repo_root, source) == "local://test/证书.pdf"

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")
    try:
        local_storage_key(repo_root, outside)
    except ValueError as error:
        assert "outside repository root" in str(error)
    else:
        raise AssertionError("仓库外文件不能生成 local storage key")


def test_apply_mode_requires_postgres() -> None:
    try:
        require_postgres_persistence(False)
    except RuntimeError as error:
        assert "PostgreSQL" in str(error)
    else:
        raise AssertionError("未配置 PostgreSQL 时不能报告 applied")
