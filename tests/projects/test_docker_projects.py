import os

import mock
import pytest

from databricks_cli.configure.provider import DatabricksConfig

import mlflow
from mlflow.entities import ViewType
from mlflow.projects import ExecutionException, _get_docker_image_uri
from mlflow.store import file_store
from mlflow.utils.mlflow_tags import MLFLOW_PROJECT_ENV, MLFLOW_DOCKER_IMAGE_URI, \
    MLFLOW_DOCKER_IMAGE_ID

from tests.projects.utils import TEST_DOCKER_PROJECT_DIR
from tests.projects.utils import docker_example_base_image  # pylint: disable=unused-import
from tests.projects.utils import tracking_uri_mock  # pylint: disable=unused-import
from mlflow.projects import _project_spec


def _build_uri(base_uri, subdirectory):
    if subdirectory != "":
        return "%s#%s" % (base_uri, subdirectory)
    return base_uri


@pytest.mark.parametrize("use_start_run", map(str, [0, 1]))
def test_docker_project_execution(
        use_start_run,
        tmpdir, tracking_uri_mock, docker_example_base_image):  # pylint: disable=unused-argument
    expected_params = {"use_start_run": use_start_run}
    submitted_run = mlflow.projects.run(
        TEST_DOCKER_PROJECT_DIR, experiment_id=file_store.FileStore.DEFAULT_EXPERIMENT_ID,
        parameters=expected_params, entry_point="test_tracking")
    # Validate run contents in the FileStore
    run_id = submitted_run.run_id
    mlflow_service = mlflow.tracking.MlflowClient()
    run_infos = mlflow_service.list_run_infos(
        experiment_id=file_store.FileStore.DEFAULT_EXPERIMENT_ID,
        run_view_type=ViewType.ACTIVE_ONLY)
    assert len(run_infos) == 1
    store_run_id = run_infos[0].run_id
    assert run_id == store_run_id
    run = mlflow_service.get_run(run_id)
    assert run.data.params == expected_params
    assert run.data.metrics == {"some_key": 3}
    exact_expected_tags = {MLFLOW_PROJECT_ENV: "docker"}
    approx_expected_tags = {
        MLFLOW_DOCKER_IMAGE_URI: "docker-example",
        MLFLOW_DOCKER_IMAGE_ID: "sha256:",
    }
    run_tags = run.data.tags
    for k, v in exact_expected_tags.items():
        assert run_tags[k] == v
    for k, v in approx_expected_tags.items():
        assert run_tags[k].startswith(v)
    artifacts = mlflow_service.list_artifacts(run_id=run_id)
    assert len(artifacts) == 1


@pytest.mark.parametrize("tracking_uri, expected_command_segment", [
    (None, "-e MLFLOW_TRACKING_URI=/mlflow/tmp/mlruns"),
    ("http://some-tracking-uri", "-e MLFLOW_TRACKING_URI=http://some-tracking-uri"),
    ("databricks://some-profile", "-e MLFLOW_TRACKING_URI=databricks ")
])
@mock.patch('databricks_cli.configure.provider.ProfileConfigProvider')
def test_docker_project_tracking_uri_propagation(
        ProfileConfigProvider, tmpdir, tracking_uri,
        expected_command_segment, docker_example_base_image):  # pylint: disable=unused-argument
    mock_provider = mock.MagicMock()
    mock_provider.get_config.return_value = \
        DatabricksConfig("host", "user", "pass", None, insecure=True)
    ProfileConfigProvider.return_value = mock_provider
    # Create and mock local tracking directory
    local_tracking_dir = os.path.join(tmpdir.strpath, "mlruns")
    if tracking_uri is None:
        tracking_uri = local_tracking_dir
    old_uri = mlflow.get_tracking_uri()
    try:
        mlflow.set_tracking_uri(tracking_uri)
        with mock.patch("mlflow.tracking.utils._get_store") as _get_store_mock:
            _get_store_mock.return_value = file_store.FileStore(local_tracking_dir)
            mlflow.projects.run(
                TEST_DOCKER_PROJECT_DIR, experiment_id=file_store.FileStore.DEFAULT_EXPERIMENT_ID)
    finally:
        mlflow.set_tracking_uri(old_uri)


def test_docker_uri_mode_validation(
        tracking_uri_mock, docker_example_base_image):  # pylint: disable=unused-argument
    with pytest.raises(ExecutionException):
        mlflow.projects.run(TEST_DOCKER_PROJECT_DIR, backend="databricks")


@mock.patch('mlflow.projects._get_git_commit')
def test_docker_image_uri_with_git(get_git_commit_mock):
    get_git_commit_mock.return_value = '1234567890'
    image_uri = _get_docker_image_uri("my_project", "my_workdir")
    assert image_uri == "my_project:1234567"
    get_git_commit_mock.assert_called_with('my_workdir')


@mock.patch('mlflow.projects._get_git_commit')
def test_docker_image_uri_no_git(get_git_commit_mock):
    get_git_commit_mock.return_value = None
    image_uri = _get_docker_image_uri("my_project", "my_workdir")
    assert image_uri == "my_project"
    get_git_commit_mock.assert_called_with('my_workdir')


def test_docker_valid_project_backend_local():
    work_dir = "./examples/docker"
    project = _project_spec.load_project(work_dir)
    mlflow.projects._validate_docker_env(project)


def test_docker_invalid_project_backend_local():
    work_dir = "./examples/docker"
    project = _project_spec.load_project(work_dir)
    project.name = None
    with pytest.raises(ExecutionException):
        mlflow.projects._validate_docker_env(project)


@pytest.mark.parametrize("artifact_uri, host_artifact_uri, container_artifact_uri, should_mount", [
    ("/tmp/mlruns/artifacts", "/tmp/mlruns/artifacts", "/tmp/mlruns/artifacts", True),
    ("s3://my_bucket", None, None, False),
    ("file:///tmp/mlruns/artifacts", "/tmp/mlruns/artifacts", "/tmp/mlruns/artifacts", True),
    ("./mlruns", os.path.abspath("./mlruns"), "/mlflow/projects/code/mlruns", True)
])
def test_docker_mount_local_artifact_uri(artifact_uri, host_artifact_uri,
                                         container_artifact_uri, should_mount):
    active_run = mock.MagicMock()
    run_info = mock.MagicMock()
    run_info.run_id = "fake_run_id"
    run_info.experiment_id = "fake_experiment_id"
    run_info.artifact_uri = artifact_uri
    active_run.info = run_info
    image = mock.MagicMock()
    image.tags = ["image:tag"]

    docker_command = mlflow.projects._get_docker_command(image, active_run)

    docker_volume_expected = "-v {}:{}".format(host_artifact_uri, container_artifact_uri)
    assert (docker_volume_expected in " ".join(docker_command)) == should_mount
