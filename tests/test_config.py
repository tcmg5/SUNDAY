from jarvis.config import DEFAULTS, _deep_merge, load_config, safe_roots


def test_deep_merge_preserves_unspecified_keys():
    merged = _deep_merge(DEFAULTS, {"tts": {"engine": "elevenlabs"}})
    assert merged["tts"]["engine"] == "elevenlabs"
    # Sibling keys in the same section must survive.
    assert merged["tts"]["piper_voice"] == DEFAULTS["tts"]["piper_voice"]
    # Other sections must be untouched.
    assert merged["wake"]["model"] == "hey_jarvis"


def test_deep_merge_does_not_mutate_defaults():
    _deep_merge(DEFAULTS, {"tts": {"engine": "none"}})
    assert DEFAULTS["tts"]["engine"] == "piper"


def test_yaml_config_overrides_defaults(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("assistant:\n  address_user_as: Tony\nwake:\n  threshold: 0.7\n")
    cfg = load_config(cfg_file)
    assert cfg["assistant"]["address_user_as"] == "Tony"
    assert cfg["wake"]["threshold"] == 0.7
    assert cfg["assistant"]["model"] == DEFAULTS["assistant"]["model"]


def test_env_override_coerces_types(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_WAKE_THRESHOLD", "0.8")
    monkeypatch.setenv("JARVIS_WAKE_ENABLED", "false")
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg["wake"]["threshold"] == 0.8
    assert cfg["wake"]["enabled"] is False


def test_secrets_come_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg["secrets"]["anthropic_api_key"] == "sk-ant-test"


def test_safe_roots_drops_nonexistent(tmp_path):
    real = tmp_path / "Real"
    real.mkdir()
    cfg = {"files": {"safe_roots": [str(real), str(tmp_path / "Imaginary")]}}
    roots = safe_roots(cfg)
    assert roots == [real.resolve()]
