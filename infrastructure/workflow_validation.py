from __future__ import annotations

from dataclasses import dataclass

SMOKE_REQUIRED_UPDATE_FIELDS = (
    "current_version",
    "current_tag",
    "runtime_status",
    "status",
    "update_available",
    "manual_update_required",
)

CANONICAL_NODE_TEST_COMMAND = "npm --prefix ai/node_runner run test"


@dataclass(frozen=True)
class ValidationWorkflowInputs:
    image_version: str
    image_tag: str
    image_build: str
    run_smoke: bool
    release_mode: bool


def normalize_workflow_inputs(
    *,
    image_version: str,
    image_tag: str,
    image_build: str,
    run_smoke: bool,
    release_mode: bool,
) -> ValidationWorkflowInputs:
    return ValidationWorkflowInputs(
        image_version=image_version.strip(),
        image_tag=image_tag.strip(),
        image_build=image_build.strip(),
        run_smoke=bool(run_smoke),
        release_mode=bool(release_mode),
    )


def validated_image_ref(inputs: ValidationWorkflowInputs) -> str:
    return "temodar-agent:release-validation" if inputs.release_mode else "temodar-agent:ci-validation"


def runtime_contract_output(inputs: ValidationWorkflowInputs) -> str:
    return "true" if inputs.run_smoke else "false"
