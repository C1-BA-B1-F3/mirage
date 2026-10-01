# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import pytest

from mirage.vfs.hf_buckets.config import HfBucketsConfig
from mirage.vfs.hf_datasets.config import HfDatasetsConfig
from mirage.vfs.hf_models.config import HfModelsConfig
from mirage.vfs.hf_spaces.config import HfSpacesConfig
from mirage.vfs.secrets import reveal_secret

REPO_CONFIGS = [HfModelsConfig, HfDatasetsConfig, HfSpacesConfig]


def test_bucket_config_defaults():
    cfg = HfBucketsConfig(bucket="myorg/mybkt")
    assert cfg.bucket == "myorg/mybkt"
    assert cfg.namespace == "myorg"
    assert cfg.bucket_name == "mybkt"
    assert cfg.token is None
    assert cfg.endpoint == "https://huggingface.co"
    assert cfg.timeout == 30
    assert cfg.key_prefix is None


def test_bucket_config_immutable():
    cfg = HfBucketsConfig(bucket="myorg/mybkt")
    with pytest.raises(Exception):
        cfg.bucket = "other/other"


@pytest.mark.parametrize(
    "bad", ["just-one-segment", "too/many/slashes", "/leading"]
)
def test_bucket_config_rejects_bad_bucket_format(bad):
    with pytest.raises(ValueError):
        HfBucketsConfig(bucket=bad)


def test_bucket_config_token_secret():
    cfg = HfBucketsConfig(bucket="myorg/mybkt", token="hf_abc123")
    assert reveal_secret(cfg.token) == "hf_abc123"
    assert "hf_abc123" not in repr(cfg)


def test_bucket_key_prefix_normalized():
    cfg = HfBucketsConfig(bucket="myorg/mybkt", key_prefix="/data/sub/")
    assert cfg.key_prefix == "data/sub/"


@pytest.mark.parametrize("config_cls", REPO_CONFIGS)
def test_repo_config_defaults(config_cls):
    cfg = config_cls(repo_id="org/repo")
    assert cfg.repo_id == "org/repo"
    assert cfg.namespace == "org"
    assert cfg.repo_name == "repo"
    assert cfg.token is None
    assert cfg.endpoint == "https://huggingface.co"
    assert cfg.key_prefix is None
    assert cfg.revision is None


@pytest.mark.parametrize("config_cls", REPO_CONFIGS)
def test_repo_config_accepts_a_bare_repo_id(config_cls):
    """The Hub resolves a bare name against whoever the token belongs
    to, and the real CLI relies on it: `hf repo create widget` then
    `hf download widget`. Refusing it rejected an id the Hub had just
    minted."""
    cfg = config_cls(repo_id="widget")
    assert cfg.repo_id == "widget"
    assert cfg.namespace == ""
    assert cfg.repo_name == "widget"


@pytest.mark.parametrize("config_cls", REPO_CONFIGS)
@pytest.mark.parametrize("bad", ["a/b/c", "ns/", "/name", ""])
def test_repo_config_rejects_a_shape_the_hub_cannot_read(config_cls, bad):
    with pytest.raises(ValueError):
        config_cls(repo_id=bad)


@pytest.mark.parametrize("config_cls", REPO_CONFIGS)
def test_repo_config_token_secret(config_cls):
    cfg = config_cls(repo_id="org/repo", token="hf_abc123")
    assert reveal_secret(cfg.token) == "hf_abc123"
    assert "hf_abc123" not in repr(cfg)


@pytest.mark.parametrize("config_cls", REPO_CONFIGS)
def test_repo_key_prefix_normalized(config_cls):
    cfg = config_cls(repo_id="org/repo", key_prefix="/data/sub/")
    assert cfg.key_prefix == "data/sub/"
