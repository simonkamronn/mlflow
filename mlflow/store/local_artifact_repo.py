import distutils.dir_util as dir_util
import os
import shutil

from six.moves import urllib

from mlflow.store.artifact_repo import ArtifactRepository
from mlflow.utils.file_utils import mkdir, list_all, get_file_info
from mlflow.utils.validation import path_not_unique, bad_path_message


class LocalArtifactRepository(ArtifactRepository):
    """Stores artifacts as files in a local directory."""
    def __init__(self, *args, **kwargs):
        super(LocalArtifactRepository, self).__init__(*args, **kwargs)

        parsed_url = urllib.parse.urlparse(self.artifact_uri)
        if parsed_url.scheme != "":
            #  Windows paths are not registered as url paths.
            #  file:(//)DRIVE://file\path\file.txt" is parsed with "file\path\file.txt" as netloc
            self.artifact_dir = parsed_url.path if os.sep == "/" else parsed_url.netloc
        else:
            self.artifact_dir = self.artifact_uri

    def get_path_module(self):
        import os
        return os.path

    def log_artifact(self, local_file, artifact_path=None):
        if artifact_path and path_not_unique(artifact_path):
            raise Exception("Invalid artifact path: '%s'. %s" % (artifact_path,
                                                                 bad_path_message(artifact_path)))
        artifact_dir = self.get_path_module().join(self.artifact_dir, artifact_path) \
            if artifact_path else self.artifact_dir

        if not self.get_path_module().exists(artifact_dir):
            mkdir(artifact_dir)
        shutil.copy(local_file, artifact_dir)

    def log_artifacts(self, local_dir, artifact_path=None):
        if artifact_path and path_not_unique(artifact_path):
            raise Exception("Invalid artifact path: '%s'. %s" % (artifact_path,
                                                                 bad_path_message(artifact_path)))
        artifact_dir = self.get_path_module().join(self.artifact_dir, artifact_path) \
            if artifact_path else self.artifact_dir
        if not self.get_path_module().exists(artifact_dir):
            mkdir(artifact_dir)
        dir_util.copy_tree(src=local_dir, dst=artifact_dir)

    def list_artifacts(self, path=None):
        list_dir = self.get_path_module().join(self.artifact_dir, path) if path else self.artifact_dir
        if self.get_path_module().isdir(list_dir):
            artifact_files = list_all(list_dir, full_path=True)
            infos = [get_file_info(f, self.get_path_module().relpath(f, self.artifact_dir))
                     for f in artifact_files]
            return sorted(infos, key=lambda f: f.path)
        else:
            return []

    def _download_file(self, remote_file_path, local_path):
        shutil.copyfile(
            self.get_path_module().join(self.artifact_dir, remote_file_path), local_path)
