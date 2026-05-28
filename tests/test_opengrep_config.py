"""Tests for .opengrep.yml — Semgrep/OpenGrep security rule configuration.

Validates rule schema, required fields, severity/language enumerations,
metadata completeness, and per-rule pattern content for all 13 rules
introduced in this configuration file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).parent.parent
OPENGREP_PATH = ROOT / ".opengrep.yml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_SEVERITIES = {"ERROR", "WARNING", "INFO"}
VALID_LANGUAGES = {
    "python",
    "typescript",
    "javascript",
    "bash",
    "go",
    "java",
    "ruby",
    "c",
    "cpp",
    "rust",
    "json",
    "yaml",
}

EXPECTED_RULE_IDS = {
    "pt-no-shell-true",
    "pt-no-yaml-load",
    "pt-no-eval",
    "pt-no-hardcoded-secret-env",
    "pt-no-deprecated-pydantic-validator",
    "pt-path-traversal-guard",
    "pt-no-bind-all-interfaces",
    "pt-sql-injection",
    "pt-ts-no-eval",
    "pt-ts-no-shell-exec",
    "pt-ts-no-hardcoded-secret",
    "pt-bash-unquoted-var",
}


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    """Load and return the parsed .opengrep.yml content."""
    assert OPENGREP_PATH.exists(), f".opengrep.yml not found at {OPENGREP_PATH}"
    with OPENGREP_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def rules(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the list of rules from the config."""
    return config["rules"]


@pytest.fixture(scope="module")
def rules_by_id(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return a mapping of rule id -> rule dict."""
    return {r["id"]: r for r in rules}


# ---------------------------------------------------------------------------
# Top-level structure
# ---------------------------------------------------------------------------


def test_config_file_exists():
    assert OPENGREP_PATH.exists(), ".opengrep.yml must exist at repository root"


def test_config_is_valid_yaml():
    with OPENGREP_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), "Top-level YAML must be a mapping"


def test_config_has_rules_key(config: dict[str, Any]):
    assert "rules" in config, "Config must have a top-level 'rules' key"


def test_rules_is_a_list(config: dict[str, Any]):
    assert isinstance(config["rules"], list), "'rules' must be a list"


def test_rules_are_not_empty(rules: list[dict[str, Any]]):
    assert len(rules) > 0, "rules list must not be empty"


def test_exact_rule_count(rules: list[dict[str, Any]]):
    assert len(rules) == 12, (
        f"Expected 12 rules, got {len(rules)}"
    )


# ---------------------------------------------------------------------------
# Rule IDs
# ---------------------------------------------------------------------------


def test_all_expected_rule_ids_present(rules_by_id: dict[str, dict[str, Any]]):
    missing = EXPECTED_RULE_IDS - set(rules_by_id.keys())
    assert missing == set(), f"Missing expected rule IDs: {missing}"


def test_no_unexpected_rule_ids(rules_by_id: dict[str, dict[str, Any]]):
    extra = set(rules_by_id.keys()) - EXPECTED_RULE_IDS
    assert extra == set(), f"Unexpected rule IDs found: {extra}"


def test_no_duplicate_rule_ids(rules: list[dict[str, Any]]):
    ids = [r["id"] for r in rules]
    duplicates = {rid for rid in ids if ids.count(rid) > 1}
    assert duplicates == set(), f"Duplicate rule IDs: {duplicates}"


def test_rule_ids_use_pt_prefix(rules: list[dict[str, Any]]):
    for rule in rules:
        assert rule["id"].startswith("pt-"), (
            f"Rule '{rule['id']}' must use 'pt-' prefix for project namespacing"
        )


# ---------------------------------------------------------------------------
# Required fields on every rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["id", "message", "languages", "severity"])
def test_all_rules_have_required_field(
    rules: list[dict[str, Any]], field: str
):
    missing = [r["id"] for r in rules if field not in r]
    assert missing == [], f"Rules missing '{field}': {missing}"


def test_all_rules_have_pattern_or_patterns(rules: list[dict[str, Any]]):
    for rule in rules:
        has_pattern = "pattern" in rule
        has_patterns = "patterns" in rule
        assert has_pattern or has_patterns, (
            f"Rule '{rule['id']}' must have either 'pattern' or 'patterns'"
        )


def test_rules_do_not_have_both_pattern_and_patterns(rules: list[dict[str, Any]]):
    for rule in rules:
        has_pattern = "pattern" in rule
        has_patterns = "patterns" in rule
        assert not (has_pattern and has_patterns), (
            f"Rule '{rule['id']}' must not have both 'pattern' and 'patterns'"
        )


# ---------------------------------------------------------------------------
# Severity validation
# ---------------------------------------------------------------------------


def test_all_rules_have_valid_severity(rules: list[dict[str, Any]]):
    for rule in rules:
        assert rule["severity"] in VALID_SEVERITIES, (
            f"Rule '{rule['id']}' has invalid severity '{rule['severity']}'; "
            f"must be one of {VALID_SEVERITIES}"
        )


def test_error_severity_rules(rules_by_id: dict[str, dict[str, Any]]):
    error_ids = {
        "pt-no-shell-true",
        "pt-no-yaml-load",
        "pt-no-eval",
        "pt-sql-injection",
        "pt-ts-no-eval",
    }
    for rid in error_ids:
        assert rules_by_id[rid]["severity"] == "ERROR", (
            f"Rule '{rid}' must have severity ERROR"
        )


def test_warning_severity_rules(rules_by_id: dict[str, dict[str, Any]]):
    warning_ids = {
        "pt-no-hardcoded-secret-env",
        "pt-no-deprecated-pydantic-validator",
        "pt-path-traversal-guard",
        "pt-no-bind-all-interfaces",
        "pt-ts-no-shell-exec",
        "pt-ts-no-hardcoded-secret",
        "pt-bash-unquoted-var",
    }
    for rid in warning_ids:
        assert rules_by_id[rid]["severity"] == "WARNING", (
            f"Rule '{rid}' must have severity WARNING"
        )


# ---------------------------------------------------------------------------
# Language validation
# ---------------------------------------------------------------------------


def test_all_rules_have_non_empty_languages(rules: list[dict[str, Any]]):
    for rule in rules:
        assert isinstance(rule["languages"], list) and len(rule["languages"]) > 0, (
            f"Rule '{rule['id']}' must have a non-empty 'languages' list"
        )


def test_all_rules_use_valid_languages(rules: list[dict[str, Any]]):
    for rule in rules:
        for lang in rule["languages"]:
            assert lang in VALID_LANGUAGES, (
                f"Rule '{rule['id']}' uses unknown language '{lang}'"
            )


def test_python_rules_target_python_only(rules_by_id: dict[str, dict[str, Any]]):
    python_only_ids = {
        "pt-no-shell-true",
        "pt-no-yaml-load",
        "pt-no-eval",
        "pt-no-hardcoded-secret-env",
        "pt-no-deprecated-pydantic-validator",
        "pt-path-traversal-guard",
        "pt-no-bind-all-interfaces",
        "pt-sql-injection",
    }
    for rid in python_only_ids:
        assert rules_by_id[rid]["languages"] == ["python"], (
            f"Rule '{rid}' must target exactly ['python']"
        )


def test_ts_rules_target_typescript_and_javascript(rules_by_id: dict[str, dict[str, Any]]):
    ts_ids = {"pt-ts-no-eval", "pt-ts-no-shell-exec", "pt-ts-no-hardcoded-secret"}
    for rid in ts_ids:
        langs = rules_by_id[rid]["languages"]
        assert set(langs) == {"typescript", "javascript"}, (
            f"Rule '{rid}' must target typescript and javascript, got {langs}"
        )


def test_bash_rule_targets_bash(rules_by_id: dict[str, dict[str, Any]]):
    assert rules_by_id["pt-bash-unquoted-var"]["languages"] == ["bash"]


# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------


def test_all_rules_have_metadata(rules: list[dict[str, Any]]):
    for rule in rules:
        assert "metadata" in rule, f"Rule '{rule['id']}' is missing 'metadata'"


def test_all_rules_have_metadata_category(rules: list[dict[str, Any]]):
    for rule in rules:
        assert "category" in rule.get("metadata", {}), (
            f"Rule '{rule['id']}' metadata is missing 'category'"
        )


def test_security_rules_have_category_security(rules_by_id: dict[str, dict[str, Any]]):
    security_ids = {
        "pt-no-shell-true",
        "pt-no-yaml-load",
        "pt-no-eval",
        "pt-no-hardcoded-secret-env",
        "pt-path-traversal-guard",
        "pt-no-bind-all-interfaces",
        "pt-sql-injection",
        "pt-ts-no-eval",
        "pt-ts-no-shell-exec",
        "pt-ts-no-hardcoded-secret",
        "pt-bash-unquoted-var",
    }
    for rid in security_ids:
        assert rules_by_id[rid]["metadata"]["category"] == "security", (
            f"Rule '{rid}' must have metadata.category == 'security'"
        )


def test_pydantic_rule_has_correctness_category(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-no-deprecated-pydantic-validator"]
    assert rule["metadata"]["category"] == "correctness", (
        "pt-no-deprecated-pydantic-validator must have category 'correctness'"
    )


def test_pydantic_rule_has_no_owasp_metadata(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-no-deprecated-pydantic-validator"]
    assert "owasp" not in rule.get("metadata", {}), (
        "pt-no-deprecated-pydantic-validator should not have OWASP metadata"
    )


def test_security_rules_with_owasp_have_valid_owasp_format(rules: list[dict[str, Any]]):
    """Rules that carry OWASP metadata must reference a recognised OWASP Top-10 entry."""
    valid_owasp_prefixes = {
        "A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10",
    }
    for rule in rules:
        owasp = rule.get("metadata", {}).get("owasp")
        if owasp is not None:
            prefix = owasp.split(":")[0].strip()
            assert prefix in valid_owasp_prefixes, (
                f"Rule '{rule['id']}' has invalid OWASP reference '{owasp}'"
            )


def test_cwe_format_is_valid_when_present(rules: list[dict[str, Any]]):
    """Any CWE values must start with 'CWE-' followed by digits."""
    import re

    cwe_pattern = re.compile(r"^CWE-\d+$")
    for rule in rules:
        cwe = rule.get("metadata", {}).get("cwe")
        if cwe is not None:
            assert cwe_pattern.match(cwe), (
                f"Rule '{rule['id']}' has malformed CWE '{cwe}' (expected 'CWE-NNN')"
            )


# ---------------------------------------------------------------------------
# Fix field
# ---------------------------------------------------------------------------


def test_only_yaml_load_rule_has_fix(rules_by_id: dict[str, dict[str, Any]]):
    """Only pt-no-yaml-load provides an automatic fix."""
    for rid, rule in rules_by_id.items():
        if rid == "pt-no-yaml-load":
            assert "fix" in rule, "pt-no-yaml-load must have a 'fix' field"
        else:
            assert "fix" not in rule, (
                f"Rule '{rid}' should not have a 'fix' field"
            )


def test_yaml_load_fix_uses_safe_load(rules_by_id: dict[str, dict[str, Any]]):
    fix = rules_by_id["pt-no-yaml-load"]["fix"]
    assert "safe_load" in fix, (
        "pt-no-yaml-load fix must reference 'safe_load'"
    )


# ---------------------------------------------------------------------------
# Per-rule pattern content
# ---------------------------------------------------------------------------


def test_pt_no_shell_true_pattern_references_shell_true(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-no-shell-true"]
    pattern_text = str(rule.get("patterns", rule.get("pattern", "")))
    assert "shell=True" in pattern_text, (
        "pt-no-shell-true must match 'shell=True'"
    )


def test_pt_no_shell_true_pattern_references_subprocess(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-no-shell-true"]
    pattern_text = str(rule.get("patterns", rule.get("pattern", "")))
    assert "subprocess" in pattern_text, (
        "pt-no-shell-true must reference 'subprocess'"
    )


def test_pt_no_yaml_load_patterns_cover_both_arities(rules_by_id: dict[str, dict[str, Any]]):
    """Rule must cover yaml.load($X) and yaml.load($X, ...) variants."""
    patterns = rules_by_id["pt-no-yaml-load"]["patterns"]
    pattern_texts = [str(p) for p in patterns]
    joined = " ".join(pattern_texts)
    assert "yaml.load" in joined, "pt-no-yaml-load patterns must reference 'yaml.load'"
    # Both zero-extra-arg and variadic forms
    pattern_strings = [p.get("pattern", "") for p in patterns if "pattern" in p]
    assert any("yaml.load($X)" in ps for ps in pattern_strings), (
        "Must include zero-arg variant yaml.load($X)"
    )
    assert any("yaml.load($X, ...)" in ps for ps in pattern_strings), (
        "Must include variadic variant yaml.load($X, ...)"
    )


def test_pt_no_eval_uses_single_pattern(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-no-eval"]
    assert "pattern" in rule, "pt-no-eval should use single 'pattern' key"
    assert "eval(" in rule["pattern"], "pt-no-eval pattern must contain 'eval('"


def test_pt_no_hardcoded_secret_uses_metavariable_regex(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-no-hardcoded-secret-env"]
    patterns = rule["patterns"]
    pattern_types = [list(p.keys())[0] for p in patterns]
    assert "metavariable-regex" in pattern_types, (
        "pt-no-hardcoded-secret-env must use metavariable-regex to match variable names"
    )


def test_pt_no_hardcoded_secret_regex_covers_common_secret_names(
    rules_by_id: dict[str, dict[str, Any]]
):
    rule = rules_by_id["pt-no-hardcoded-secret-env"]
    mv_regex_entries = [
        p["metavariable-regex"]
        for p in rule["patterns"]
        if "metavariable-regex" in p
    ]
    assert mv_regex_entries, "Expected at least one metavariable-regex entry"
    # The first metavariable-regex targets the variable name
    var_regex = next(
        (e["regex"] for e in mv_regex_entries if e.get("metavariable") == "$VAR"),
        None,
    )
    assert var_regex is not None, "metavariable-regex must target $VAR"
    for keyword in ["api_key", "secret", "password", "token"]:
        assert keyword in var_regex.lower(), (
            f"pt-no-hardcoded-secret-env regex must cover '{keyword}'"
        )


def test_pt_path_traversal_guard_covers_os_path_join(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-path-traversal-guard"]
    pattern_text = str(rule["patterns"])
    assert "os.path.join" in pattern_text


def test_pt_path_traversal_guard_covers_pathlib_slash(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-path-traversal-guard"]
    pattern_text = str(rule["patterns"])
    assert "Path($BASE) / $USER_INPUT" in pattern_text


def test_pt_no_bind_all_interfaces_covers_uvicorn_and_flask(
    rules_by_id: dict[str, dict[str, Any]]
):
    rule = rules_by_id["pt-no-bind-all-interfaces"]
    pattern_text = str(rule["patterns"])
    assert "uvicorn.run" in pattern_text
    assert "app.run" in pattern_text
    assert "0.0.0.0" in pattern_text


def test_pt_sql_injection_covers_three_injection_vectors(rules_by_id: dict[str, dict[str, Any]]):
    """Rule must cover %-format, f-string, and concatenation vectors."""
    rule = rules_by_id["pt-sql-injection"]
    pattern_strings = [p.get("pattern", "") for p in rule["patterns"] if "pattern" in p]
    joined = " ".join(pattern_strings)
    assert "% ..." in joined, "Must cover string-percent formatting"
    assert 'f"' in joined, "Must cover f-string interpolation"
    assert '+ $VAR +' in joined, "Must cover string concatenation"


def test_pt_ts_no_eval_covers_eval_and_function_constructor(
    rules_by_id: dict[str, dict[str, Any]]
):
    rule = rules_by_id["pt-ts-no-eval"]
    pattern_strings = [p.get("pattern", "") for p in rule["patterns"] if "pattern" in p]
    joined = " ".join(pattern_strings)
    assert "eval(" in joined, "pt-ts-no-eval must match eval()"
    assert "new Function(" in joined, "pt-ts-no-eval must match new Function()"


def test_pt_ts_no_shell_exec_covers_exec_and_execsync(rules_by_id: dict[str, dict[str, Any]]):
    rule = rules_by_id["pt-ts-no-shell-exec"]
    pattern_strings = [p.get("pattern", "") for p in rule["patterns"] if "pattern" in p]
    joined = " ".join(pattern_strings)
    assert "exec(" in joined, "pt-ts-no-shell-exec must match exec()"
    assert "execSync(" in joined, "pt-ts-no-shell-exec must match execSync()"


def test_pt_ts_no_hardcoded_secret_uses_metavariable_regex(
    rules_by_id: dict[str, dict[str, Any]]
):
    rule = rules_by_id["pt-ts-no-hardcoded-secret"]
    pattern_types = [list(p.keys())[0] for p in rule["patterns"]]
    assert "metavariable-regex" in pattern_types


def test_pt_ts_no_hardcoded_secret_regex_covers_camel_and_snake_case(
    rules_by_id: dict[str, dict[str, Any]]
):
    rule = rules_by_id["pt-ts-no-hardcoded-secret"]
    mv_regex_entries = [
        p["metavariable-regex"]
        for p in rule["patterns"]
        if "metavariable-regex" in p
    ]
    var_regex = next(
        (e["regex"] for e in mv_regex_entries if e.get("metavariable") == "$VAR"),
        None,
    )
    assert var_regex is not None
    assert "apiKey" in var_regex or "api_key" in var_regex, (
        "TS hardcoded secret regex must cover both camelCase and snake_case API key names"
    )


def test_pt_bash_unquoted_var_targets_destructive_rm_rf(
    rules_by_id: dict[str, dict[str, Any]]
):
    rule = rules_by_id["pt-bash-unquoted-var"]
    pattern_text = str(rule["patterns"])
    assert "rm -rf" in pattern_text, (
        "pt-bash-unquoted-var must include 'rm -rf' destructive command pattern"
    )


# ---------------------------------------------------------------------------
# Message content spot-checks
# ---------------------------------------------------------------------------


def test_messages_are_non_empty_strings(rules: list[dict[str, Any]]):
    for rule in rules:
        msg = rule.get("message", "")
        assert isinstance(msg, str) and msg.strip(), (
            f"Rule '{rule['id']}' has an empty or missing message"
        )


def test_pt_no_shell_true_message_suggests_list_form(rules_by_id: dict[str, dict[str, Any]]):
    msg = rules_by_id["pt-no-shell-true"]["message"]
    assert "list" in msg.lower() or "subprocess.run" in msg, (
        "pt-no-shell-true message should suggest using list-form subprocess call"
    )


def test_pt_no_yaml_load_message_suggests_safe_load(rules_by_id: dict[str, dict[str, Any]]):
    msg = rules_by_id["pt-no-yaml-load"]["message"]
    assert "safe_load" in msg, (
        "pt-no-yaml-load message must recommend yaml.safe_load()"
    )


def test_pt_sql_injection_message_suggests_parameterised_queries(
    rules_by_id: dict[str, dict[str, Any]]
):
    msg = rules_by_id["pt-sql-injection"]["message"]
    assert "param" in msg.lower(), (
        "pt-sql-injection message must mention parameterised queries"
    )


def test_pt_no_bind_all_interfaces_message_suggests_localhost(
    rules_by_id: dict[str, dict[str, Any]]
):
    msg = rules_by_id["pt-no-bind-all-interfaces"]["message"]
    assert "127.0.0.1" in msg, (
        "pt-no-bind-all-interfaces message must suggest 127.0.0.1 as safer alternative"
    )


# ---------------------------------------------------------------------------
# Regression / boundary tests
# ---------------------------------------------------------------------------


def test_yaml_load_rule_has_no_extra_loader_kwarg_in_fix(
    rules_by_id: dict[str, dict[str, Any]]
):
    """Regression: fix must not accidentally pass an unsafe loader argument."""
    fix = rules_by_id["pt-no-yaml-load"]["fix"]
    # The fix should call safe_load, not pass a Loader= argument
    assert "Loader" not in fix, (
        "pt-no-yaml-load fix must not pass a Loader argument (safe_load needs none)"
    )


def test_all_error_rules_have_injection_or_integrity_owasp(
    rules_by_id: dict[str, dict[str, Any]]
):
    """All ERROR-severity rules should reference injection or integrity OWASP categories."""
    error_rules_with_owasp = {
        rid: rule
        for rid, rule in rules_by_id.items()
        if rule["severity"] == "ERROR" and "owasp" in rule.get("metadata", {})
    }
    for rid, rule in error_rules_with_owasp.items():
        owasp = rule["metadata"]["owasp"]
        # A03 = Injection, A08 = Software and Data Integrity Failures
        assert "A03" in owasp or "A08" in owasp, (
            f"ERROR rule '{rid}' OWASP reference '{owasp}' should be A03 or A08"
        )


def test_no_rule_uses_severity_info(rules: list[dict[str, Any]]):
    """INFO severity is not used — all rules are either ERROR or WARNING."""
    info_rules = [r["id"] for r in rules if r.get("severity") == "INFO"]
    assert info_rules == [], f"Unexpected INFO severity rules: {info_rules}"


def test_hardcoded_secret_regex_is_case_insensitive(rules_by_id: dict[str, dict[str, Any]]):
    """Both Python and TS secret rules must use case-insensitive regex flags."""
    for rid in ("pt-no-hardcoded-secret-env", "pt-ts-no-hardcoded-secret"):
        mv_entries = [
            p["metavariable-regex"]
            for p in rules_by_id[rid]["patterns"]
            if "metavariable-regex" in p
        ]
        var_regex = next(
            (e["regex"] for e in mv_entries if e.get("metavariable") == "$VAR"),
            None,
        )
        assert var_regex and "(?i)" in var_regex, (
            f"Rule '{rid}' must use case-insensitive flag (?i) in metavariable-regex"
        )
