from pathlib import Path

import yaml

from infrastructure.workflow_validation import (
    CANONICAL_NODE_TEST_COMMAND,
    SMOKE_REQUIRED_UPDATE_FIELDS,
    ValidationWorkflowInputs,
    normalize_workflow_inputs,
    runtime_contract_output,
    validated_image_ref,
)


ROOT = Path(__file__).resolve().parents[1]


def _read_workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def test_normalize_workflow_inputs_preserves_expected_metadata_values():
    inputs = normalize_workflow_inputs(
        image_version=" 0.1.3 ",
        image_tag=" v0.1.3 ",
        image_build=" sha-123 ",
        run_smoke=True,
        release_mode=False,
    )

    assert inputs == ValidationWorkflowInputs(
        image_version="0.1.3",
        image_tag="v0.1.3",
        image_build="sha-123",
        run_smoke=True,
        release_mode=False,
    )


def test_smoke_required_update_fields_match_contract_expectations():
    assert SMOKE_REQUIRED_UPDATE_FIELDS == (
        "current_version",
        "current_tag",
        "runtime_status",
        "status",
        "update_available",
        "manual_update_required",
    )


def test_runtime_contract_output_tracks_smoke_setting():
    assert runtime_contract_output(
        ValidationWorkflowInputs("ci", "main", "sha-1", True, False)
    ) == "true"
    assert runtime_contract_output(
        ValidationWorkflowInputs("ci", "main", "sha-1", False, False)
    ) == "false"


def test_validated_image_ref_matches_validation_mode():
    assert validated_image_ref(
        ValidationWorkflowInputs("ci", "main", "sha-1", True, False)
    ) == "temodar-agent:ci-validation"
    assert validated_image_ref(
        ValidationWorkflowInputs("0.1.3", "v0.1.3", "sha-1", True, True)
    ) == "temodar-agent:release-validation"


def test_reusable_validation_workflow_runs_shared_validation_chain():
    workflow = _read_workflow("reusable-validate.yml")
    workflow_call = workflow[True]["workflow_call"]
    inputs = workflow_call["inputs"]
    outputs = workflow_call["outputs"]
    job = workflow["jobs"]["validate"]
    steps = job["steps"]
    step_names = [step["name"] for step in steps]

    assert set(inputs) == {
        "image_version",
        "image_tag",
        "image_build",
        "run_smoke",
        "release_mode",
    }
    assert set(outputs) == {"validated_image_ref", "runtime_contract_ok"}
    assert step_names == [
        "Checkout repository",
        "Resolve validated image reference",
        "Set up Python",
        "Set up Node.js",
        "Install Python dependencies",
        "Install Node dependencies",
        "Build Node runner",
        "Run Node tests",
        "Run Python tests",
        "Build Docker image",
        "Smoke test Docker image",
        "Emit smoke result for callers",
    ]
    assert steps[7]["run"] == CANONICAL_NODE_TEST_COMMAND


def test_reusable_validation_workflow_uses_one_canonical_node_test_command_for_all_parity_runs():
    workflow = _read_workflow("reusable-validate.yml")
    run_node_tests_step = workflow["jobs"]["validate"]["steps"][7]

    assert run_node_tests_step["name"] == "Run Node tests"
    assert run_node_tests_step["run"] == CANONICAL_NODE_TEST_COMMAND


def test_node_runner_package_test_script_matches_canonical_workflow_command():
    package = yaml.safe_load((ROOT / "ai" / "node_runner" / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["test"] == "node --import tsx --test --test-force-exit test/node_runner.test.ts"
    assert CANONICAL_NODE_TEST_COMMAND == "npm --prefix ai/node_runner run test"
    assert "--test-force-exit" in package["scripts"]["test"]


def test_ci_workflow_preserves_push_pr_and_manual_triggers():
    workflow = _read_workflow("ci.yml")
    triggers = workflow[True]

    assert triggers == {
        "pull_request": {"branches": ["main"]},
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    }



def test_ci_workflow_calls_reusable_validation_with_ci_metadata():
    workflow = _read_workflow("ci.yml")
    validate_job = workflow["jobs"]["validate"]

    assert validate_job["uses"] == "./.github/workflows/reusable-validate.yml"
    assert validate_job["with"] == {
        "image_version": "ci",
        "image_tag": "${{ github.ref_name }}",
        "image_build": "${{ github.sha }}",
        "run_smoke": True,
        "release_mode": False,
    }



def test_ci_workflow_remains_a_thin_caller_without_inline_validation_steps():
    workflow = _read_workflow("ci.yml")
    validate_job = workflow["jobs"]["validate"]

    assert set(workflow["jobs"]) == {"validate"}
    assert "steps" not in validate_job
    assert set(validate_job) == {"uses", "with"}



def test_release_workflow_routes_publish_through_reusable_validation():
    workflow = _read_workflow("docker-publish.yml")
    metadata_job = workflow["jobs"]["metadata"]
    validate_job = workflow["jobs"]["validate"]
    publish_job = workflow["jobs"]["publish"]

    assert metadata_job["outputs"] == {
        "app_version": "${{ steps.meta.outputs.app_version }}",
        "git_tag": "${{ steps.meta.outputs.git_tag }}",
        "minor_tag": "${{ steps.meta.outputs.minor_tag }}",
        "publish_latest": "${{ steps.meta.outputs.publish_latest }}",
    }
    assert validate_job["needs"] == "metadata"
    assert validate_job["uses"] == "./.github/workflows/reusable-validate.yml"
    assert validate_job["with"] == {
        "image_version": "${{ needs.metadata.outputs.app_version }}",
        "image_tag": "${{ needs.metadata.outputs.git_tag }}",
        "image_build": "${{ github.sha }}",
        "run_smoke": True,
        "release_mode": True,
    }
    assert validate_job["with"]["release_mode"] is True
    assert validate_job["with"]["run_smoke"] is True
    assert publish_job["needs"] == ["metadata", "validate"]


def test_publish_job_depends_on_validation_before_push_steps():
    workflow = _read_workflow("docker-publish.yml")
    publish_job = workflow["jobs"]["publish"]
    step_names = [step["name"] for step in publish_job["steps"]]

    assert publish_job["needs"] == ["metadata", "validate"]
    assert step_names == [
        "Checkout repository",
        "Set up QEMU",
        "Set up Docker Buildx",
        "Log in to Docker Hub",
        "Set up Docker metadata",
        "Build and push multi-arch Docker image",
    ]


def test_release_workflow_keeps_dockerhub_credentials_scoped_to_publish_only_behavior():
    workflow = _read_workflow("docker-publish.yml")
    metadata_job = workflow["jobs"]["metadata"]
    validate_job = workflow["jobs"]["validate"]
    publish_job = workflow["jobs"]["publish"]

    metadata_text = yaml.safe_dump(metadata_job, sort_keys=True)
    validate_text = yaml.safe_dump(validate_job, sort_keys=True)
    publish_text = yaml.safe_dump(publish_job, sort_keys=True)

    assert "DOCKERHUB_USERNAME" not in metadata_text
    assert "DOCKERHUB_TOKEN" not in metadata_text
    assert "DOCKERHUB_USERNAME" not in validate_text
    assert "DOCKERHUB_TOKEN" not in validate_text
    assert "DOCKERHUB_USERNAME" in publish_text
    assert "DOCKERHUB_TOKEN" in publish_text



def test_release_workflow_buildx_publish_preserves_runtime_metadata_alignment():
    workflow = _read_workflow("docker-publish.yml")
    publish_job = workflow["jobs"]["publish"]
    build_and_push_step = publish_job["steps"][-1]

    assert build_and_push_step["uses"] == "docker/build-push-action@v6"
    assert build_and_push_step["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert build_and_push_step["with"]["push"] is True
    assert build_and_push_step["with"]["build-args"] == (
        "TEMODAR_AGENT_IMAGE_VERSION=${{ needs.metadata.outputs.app_version }}\n"
        "TEMODAR_AGENT_IMAGE_TAG=${{ needs.metadata.outputs.git_tag }}\n"
        "TEMODAR_AGENT_IMAGE_BUILD=${{ github.sha }}\n"
    )

    validate_with = workflow["jobs"]["validate"]["with"]
    assert validate_with["image_version"] == "${{ needs.metadata.outputs.app_version }}"
    assert validate_with["image_tag"] == "${{ needs.metadata.outputs.git_tag }}"
    assert validate_with["image_build"] == "${{ github.sha }}"
    assert validate_with["release_mode"] is True
    assert validate_with["run_smoke"] is True
    assert build_and_push_step["with"]["provenance"] is False
    assert build_and_push_step["with"]["sbom"] is False
    assert build_and_push_step["with"]["cache-from"] == "type=gha"
    assert build_and_push_step["with"]["cache-to"] == "type=gha,mode=max"
    assert build_and_push_step["with"]["tags"] == "${{ steps.docker_meta.outputs.tags }}"
    assert build_and_push_step["with"]["labels"] == "${{ steps.docker_meta.outputs.labels }}"
    assert build_and_push_step["with"]["context"] == "."



def test_reusable_validation_smoke_waits_for_health_before_update_contract():
    workflow = _read_workflow("reusable-validate.yml")
    smoke_step = workflow["jobs"]["validate"]["steps"][-2]
    run_script = smoke_step["run"]

    assert "wait_for_http http://127.0.0.1:18080/health" in run_script
    assert "curl --fail --silent http://127.0.0.1:18080/api/system/update >/tmp/temodar-system-update.json" in run_script
    assert run_script.index("wait_for_http http://127.0.0.1:18080/health") < run_script.index(
        "curl --fail --silent http://127.0.0.1:18080/api/system/update >/tmp/temodar-system-update.json"
    )


def test_reusable_validation_smoke_uses_documented_runtime_mounts():
    workflow = _read_workflow("reusable-validate.yml")
    smoke_step = workflow["jobs"]["validate"]["steps"][-2]
    run_script = smoke_step["run"]

    assert 'docker run -d --name "$name" -p 18080:8080 \\' in run_script
    assert '-v temodar-agent-validation-data:/home/appuser/.temodar-agent \\' in run_script
    assert '-v temodar-agent-validation-plugins:/app/Plugins \\' in run_script
    assert '-v temodar-agent-validation-semgrep:/app/semgrep_results \\' in run_script
    assert "docker volume create temodar-agent-validation-data" in run_script
    assert "docker volume create temodar-agent-validation-plugins" in run_script
    assert "docker volume create temodar-agent-validation-semgrep" in run_script



def test_reusable_validation_smoke_verifies_mounted_paths_are_writable():
    workflow = _read_workflow("reusable-validate.yml")
    smoke_step = workflow["jobs"]["validate"]["steps"][-2]
    run_script = smoke_step["run"]

    assert "verify_writable_mounts()" in run_script
    assert "verify_writable_mounts temodar-agent-validation-smoke" in run_script
    assert "verify_writable_mounts temodar-agent-validation-smoke-recreated" in run_script
    assert "touch /home/appuser/.temodar-agent/write-test" in run_script
    assert "touch /app/Plugins/write-test" in run_script
    assert "touch /app/semgrep_results/write-test" in run_script
    assert run_script.index("verify_writable_mounts temodar-agent-validation-smoke") < run_script.index(
        "curl --fail --silent http://127.0.0.1:18080/api/system/update >/tmp/temodar-system-update.json"
    )
    assert run_script.index("verify_writable_mounts temodar-agent-validation-smoke-recreated") < run_script.index(
        "curl --fail --silent http://127.0.0.1:18080/api/system/update >/tmp/temodar-system-update-recreated.json"
    )



def test_reusable_validation_smoke_verifies_restart_and_recreate_persistence_contract():
    workflow = _read_workflow("reusable-validate.yml")
    smoke_step = workflow["jobs"]["validate"]["steps"][-2]
    run_script = smoke_step["run"]

    assert "docker exec temodar-agent-validation-smoke python - <<'PY'" in run_script
    assert "docker restart temodar-agent-validation-smoke >/dev/null" in run_script
    assert "docker rm -f temodar-agent-validation-smoke >/dev/null" in run_script
    assert "run_container temodar-agent-validation-smoke-recreated" in run_script
    assert "curl --fail --silent http://127.0.0.1:18080/api/system/update >/tmp/temodar-system-update-recreated.json" in run_script
    assert "persisted across restart and recreate" in run_script
    assert "Path('/home/appuser/.temodar-agent/acceptance/persistence.txt')" in run_script


def test_reusable_validation_smoke_cleans_up_volume_and_containers():
    workflow = _read_workflow("reusable-validate.yml")
    smoke_step = workflow["jobs"]["validate"]["steps"][-2]
    run_script = smoke_step["run"]

    assert "docker rm -f temodar-agent-validation-smoke temodar-agent-validation-smoke-recreated >/dev/null 2>&1 || true" in run_script
    assert "docker volume rm temodar-agent-validation-data temodar-agent-validation-plugins temodar-agent-validation-semgrep >/dev/null 2>&1 || true" in run_script
    assert "trap cleanup EXIT" in run_script
    assert "docker logs temodar-agent-validation-smoke || true" in run_script
    assert "docker logs temodar-agent-validation-smoke-recreated || true" in run_script
    assert "cleanup" in run_script
    assert "trap - EXIT" in run_script


def test_reusable_validation_smoke_checks_update_contract_after_recreate():
    workflow = _read_workflow("reusable-validate.yml")
    smoke_step = workflow["jobs"]["validate"]["steps"][-2]
    run_script = smoke_step["run"]

    assert "for name in ('/tmp/temodar-system-update.json', '/tmp/temodar-system-update-recreated.json'):" in run_script
    assert "missing = required - payload.keys()" in run_script
    assert "manual_update_required" in run_script
    assert "runtime_status" in run_script
    assert "current_tag" in run_script
    assert "current_version" in run_script
    assert "update_available" in run_script
    assert "status" in run_script
    assert "Missing keys from {name}: {sorted(missing)}" in run_script
    assert run_script.index("/tmp/temodar-system-update-recreated.json") > run_script.index(
        "/tmp/temodar-system-update.json"
    )



def test_dockerfile_defines_healthcheck():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6" in dockerfile
    assert "http://127.0.0.1:8080/health" in dockerfile



def test_app_exposes_health_endpoint_as_public_route():
    app_text = (ROOT / "server" / "app.py").read_text(encoding="utf-8")

    assert '"/health"' in app_text
    assert '@app.get("/health")' in app_text
    assert 'JSONResponse({"status": "ok"})' in app_text



def test_health_endpoint_returns_ok(monkeypatch):
    monkeypatch.setattr(
        "server.app.update_manager.manager.get_status",
        lambda force=False: {"status": "ok"},
    )
    monkeypatch.setattr(
        "server.app.ensure_db_dir",
        lambda path=None: Path("/Users/xeloxa/Desktop/temodar-agent/.pytest-task05-workflow.db"),
    )
    from fastapi.testclient import TestClient
    from server.app import create_app

    client = TestClient(create_app(), base_url="http://localhost")
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"].startswith("application/json")
    assert response.request.url.path == "/health"
    assert response.request.headers["host"] == "localhost"
    assert response.request.method == "GET"
    assert response.request.url.scheme == "http"
    assert str(response.request.url).startswith("http://localhost/health")
    assert response.request.headers["accept"] == "*/*"
    assert response.request.headers["connection"] == "keep-alive"
    assert response.request.headers["user-agent"]
    assert client.headers.get("host", "") == ""



def test_release_workflow_metadata_derivation_checks_tag_to_version_alignment():
    workflow = _read_workflow("docker-publish.yml")
    derive_release_metadata_step = workflow["jobs"]["metadata"]["steps"][2]
    run_script = derive_release_metadata_step["run"]

    assert 'GIT_TAG="${GITHUB_REF_NAME}"' in run_script
    assert 'CLEAN_TAG="${GIT_TAG#v}"' in run_script
    assert 'if [[ "${APP_VERSION}" != "${CLEAN_TAG}" ]]; then' in run_script
    assert 'echo "Tag ${GIT_TAG} does not match app_meta.py version ${APP_VERSION}" >&2' in run_script
    assert '{' in run_script
    assert 'echo "app_version=${APP_VERSION}"' in run_script
    assert 'echo "git_tag=${GIT_TAG}"' in run_script
    assert 'echo "minor_tag=${MINOR_TAG}"' in run_script
    assert '} >> "${GITHUB_OUTPUT}"' in run_script
