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
        "publish_artifact_name",
    }
    assert set(outputs) == {"validated_image_ref", "runtime_contract_ok", "validated_image_artifact"}
    assert step_names == [
        "Checkout repository",
        "Resolve validated image reference",
        "Resolve validated image artifact name",
        "Set up Python",
        "Set up Node.js",
        "Install Python dependencies",
        "Install Node dependencies",
        "Build Node runner",
        "Run Node tests",
        "Run Python tests",
        "Build Docker image",
        "Smoke test Docker image",
        "Export validated image",
        "Upload validated image artifact",
        "Emit smoke result for callers",
    ]
    assert steps[8]["run"] == CANONICAL_NODE_TEST_COMMAND


def test_reusable_validation_workflow_uses_one_canonical_node_test_command_for_all_parity_runs():
    workflow = _read_workflow("reusable-validate.yml")
    run_node_tests_step = workflow["jobs"]["validate"]["steps"][8]

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
        "publish_artifact_name": "validated-release-image",
    }
    assert publish_job["needs"] == ["metadata", "validate"]


def test_publish_job_depends_on_validation_before_push_steps():
    workflow = _read_workflow("docker-publish.yml")
    publish_job = workflow["jobs"]["publish"]
    step_names = [step["name"] for step in publish_job["steps"]]

    assert publish_job["needs"] == ["metadata", "validate"]
    assert step_names == [
        "Download validated image artifact",
        "Load validated image",
        "Set up Docker Buildx",
        "Log in to Docker Hub",
        "Set up Docker metadata",
        "Apply release tags to validated image",
        "Push validated image tags",
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



def test_release_workflow_publish_tags_preserve_runtime_metadata_alignment():
    workflow = _read_workflow("docker-publish.yml")
    publish_job = workflow["jobs"]["publish"]
    apply_release_tags_step = publish_job["steps"][-2]

    run_script = apply_release_tags_step["run"]
    assert 'docker tag "${{ needs.validate.outputs.validated_image_ref }}" "$tag"' in run_script
    assert 'done <<< "${{ steps.docker_meta.outputs.tags }}"' in run_script

    validate_with = workflow["jobs"]["validate"]["with"]
    assert validate_with["image_version"] == "${{ needs.metadata.outputs.app_version }}"
    assert validate_with["image_tag"] == "${{ needs.metadata.outputs.git_tag }}"
    assert validate_with["image_build"] == "${{ github.sha }}"
    assert validate_with["release_mode"] is True
    assert validate_with["run_smoke"] is True
    assert validate_with["publish_artifact_name"] == "validated-release-image"



def test_release_workflow_metadata_derivation_checks_tag_to_version_alignment():
    workflow = _read_workflow("docker-publish.yml")
    derive_release_metadata_step = workflow["jobs"]["metadata"]["steps"][2]
    run_script = derive_release_metadata_step["run"]

    assert 'GIT_TAG="${GITHUB_REF_NAME}"' in run_script
    assert 'CLEAN_TAG="${GIT_TAG#v}"' in run_script
    assert 'if [[ "${APP_VERSION}" != "${CLEAN_TAG}" ]]; then' in run_script
    assert 'echo "Tag ${GIT_TAG} does not match app_meta.py version ${APP_VERSION}" >&2' in run_script
    assert 'echo "app_version=${APP_VERSION}" >> "${GITHUB_OUTPUT}"' in run_script
    assert 'echo "git_tag=${GIT_TAG}" >> "${GITHUB_OUTPUT}"' in run_script
    assert 'echo "minor_tag=${MINOR_TAG}" >> "${GITHUB_OUTPUT}"' in run_script
