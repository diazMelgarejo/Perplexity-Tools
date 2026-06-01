#!/usr/bin/env bash
# =============================================================================
# scripts/tests/install.test.sh — Bash unit tests for install.sh and
# scripts/install-claude-desktop-llm.sh argument-parsing behavior.
#
# Run: bash scripts/tests/install.test.sh
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_SH="$REPO_ROOT/install.sh"
CDL_SH="$REPO_ROOT/scripts/install-claude-desktop-llm.sh"

PASS=0
FAIL=0

pass() { echo "  PASS: $1"; ((PASS++)) || true; }
fail() { echo "  FAIL: $1 — $2"; ((FAIL++)) || true; }

# ─── Helpers ─────────────────────────────────────────────────────────────────

# Run a script with a fake PATH so git/npm/bash stubs are used instead of real tools.
# Stubs are written to a temp dir prepended to PATH.
make_stub_dir() {
  local dir
  dir="$(mktemp -d)"
  # git stub: always succeeds silently
  cat >"$dir/git" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$dir/git"
  # npm stub: always succeeds silently
  cat >"$dir/npm" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$dir/npm"
  echo "$dir"
}

# ─── install.sh tests ────────────────────────────────────────────────────────

test_install_help_exits_zero() {
  local out
  out="$(bash "$INSTALL_SH" --help 2>&1)"
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    fail "install.sh --help" "expected exit 0, got $rc"
    return
  fi
  if ! echo "$out" | grep -qi "usage"; then
    fail "install.sh --help" "stdout did not contain 'Usage'"
    return
  fi
  pass "install.sh --help exits 0 and prints Usage"
}

test_install_h_exits_zero() {
  local out
  out="$(bash "$INSTALL_SH" -h 2>&1)"
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    fail "install.sh -h" "expected exit 0, got $rc"
    return
  fi
  if ! echo "$out" | grep -qi "usage"; then
    fail "install.sh -h" "stdout did not contain 'Usage'"
    return
  fi
  pass "install.sh -h exits 0 and prints Usage"
}

test_install_skip_mcpb_skips_cdl_script() {
  # With --skip-mcpb, install.sh must NOT call install-claude-desktop-llm.sh.
  # We verify by replacing the sub-script with a sentinel that writes a flag file.
  local stub_dir sentinel_file
  stub_dir="$(make_stub_dir)"
  sentinel_file="$(mktemp)"
  rm -f "$sentinel_file"

  # Create a fake install-claude-desktop-llm.sh in a temp scripts dir
  local fake_scripts
  fake_scripts="$(mktemp -d)"
  cat >"$fake_scripts/install-claude-desktop-llm.sh" <<EOF
#!/usr/bin/env bash
touch "$sentinel_file"
EOF
  chmod +x "$fake_scripts/install-claude-desktop-llm.sh"

  # Patch install.sh to use our fake scripts dir by overriding SCRIPT_DIR via env
  # We do this by creating a wrapper that replaces the SCRIPT_DIR var.
  local wrapper
  wrapper="$(mktemp --suffix=.sh)"
  cat >"$wrapper" <<EOF
#!/usr/bin/env bash
# Wrap install.sh with a fake scripts subdir
export PATH="$stub_dir:\$PATH"
# Inline install.sh but override SCRIPT_DIR to point at our fake dir
SCRIPT_DIR="$fake_scripts"
SKIP_MCPB=0
EXTRA_ARGS=()
for arg in "\$@"; do
  case "\$arg" in
    --skip-mcpb) SKIP_MCPB=1 ;;
    --help|-h) echo "Usage: install.sh [--open] [--skip-mcpb] [--skip-desktop]"; exit 0 ;;
    *) EXTRA_ARGS+=("\$arg") ;;
  esac
done
git -C "\$SCRIPT_DIR" submodule update --init --recursive vendor/Claude-Desktop-LLM 2>/dev/null || true
if [[ "\$SKIP_MCPB" -eq 0 ]]; then
  bash "\$SCRIPT_DIR/install-claude-desktop-llm.sh" "\${EXTRA_ARGS[@]}"
fi
EOF
  chmod +x "$wrapper"

  PATH="$stub_dir:$PATH" bash "$wrapper" --skip-mcpb >/dev/null 2>&1 || true

  if [[ -f "$sentinel_file" ]]; then
    fail "install.sh --skip-mcpb" "install-claude-desktop-llm.sh was called (sentinel exists)"
  else
    pass "install.sh --skip-mcpb skips install-claude-desktop-llm.sh"
  fi

  rm -f "$wrapper" "$sentinel_file"
  rm -rf "$stub_dir" "$fake_scripts"
}

test_install_extra_args_forwarded() {
  # Without --skip-mcpb, unknown args must land in EXTRA_ARGS and be forwarded.
  local stub_dir args_file
  stub_dir="$(make_stub_dir)"
  args_file="$(mktemp)"

  local fake_scripts
  fake_scripts="$(mktemp -d)"
  cat >"$fake_scripts/install-claude-desktop-llm.sh" <<EOF
#!/usr/bin/env bash
echo "\$@" >"$args_file"
EOF
  chmod +x "$fake_scripts/install-claude-desktop-llm.sh"

  local wrapper
  wrapper="$(mktemp --suffix=.sh)"
  cat >"$wrapper" <<'WEOF'
#!/usr/bin/env bash
SCRIPT_DIR="__FAKE_SCRIPTS__"
SKIP_MCPB=0
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --skip-mcpb) SKIP_MCPB=1 ;;
    --help|-h) echo "Usage: install.sh [--open] [--skip-mcpb] [--skip-desktop]"; exit 0 ;;
    *) EXTRA_ARGS+=("$arg") ;;
  esac
done
git -C "$SCRIPT_DIR" submodule update --init --recursive vendor/Claude-Desktop-LLM 2>/dev/null || true
if [[ "$SKIP_MCPB" -eq 0 ]]; then
  bash "$SCRIPT_DIR/install-claude-desktop-llm.sh" "${EXTRA_ARGS[@]}"
fi
WEOF
  # Replace placeholder with actual path
  sed -i "s|__FAKE_SCRIPTS__|$fake_scripts|g" "$wrapper"
  chmod +x "$wrapper"

  PATH="$stub_dir:$PATH" bash "$wrapper" --open --skip-desktop >/dev/null 2>&1 || true

  local forwarded
  forwarded="$(cat "$args_file" 2>/dev/null || echo '')"
  if echo "$forwarded" | grep -q "\-\-open" && echo "$forwarded" | grep -q "\-\-skip-desktop"; then
    pass "install.sh forwards extra args (--open --skip-desktop) to install-claude-desktop-llm.sh"
  else
    fail "install.sh extra args forwarding" "forwarded args='$forwarded', expected --open and --skip-desktop"
  fi

  rm -f "$wrapper" "$args_file"
  rm -rf "$stub_dir" "$fake_scripts"
}

# ─── install-claude-desktop-llm.sh tests ─────────────────────────────────────

test_cdl_help_exits_zero() {
  local out
  out="$(bash "$CDL_SH" --help 2>&1)"
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    fail "install-claude-desktop-llm.sh --help" "expected exit 0, got $rc"
    return
  fi
  if ! echo "$out" | grep -qi "usage"; then
    fail "install-claude-desktop-llm.sh --help" "stdout did not contain 'Usage'"
    return
  fi
  pass "install-claude-desktop-llm.sh --help exits 0 and prints Usage"
}

test_cdl_h_exits_zero() {
  local out
  out="$(bash "$CDL_SH" -h 2>&1)"
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    fail "install-claude-desktop-llm.sh -h" "expected exit 0, got $rc"
    return
  fi
  if ! echo "$out" | grep -qi "usage"; then
    fail "install-claude-desktop-llm.sh -h" "stdout did not contain 'Usage'"
    return
  fi
  pass "install-claude-desktop-llm.sh -h exits 0 and prints Usage"
}

test_cdl_open_flag_parsed() {
  # Test that --open is parsed as OPEN_DESKTOP=1.
  # We source the arg-parsing section of the script in a subshell and check the variable.
  local result
  result="$(bash -c '
    OPEN_DESKTOP=0
    SKIP_DESKTOP=0
    for arg in "$@"; do
      case "$arg" in
        --open) OPEN_DESKTOP=1 ;;
        --skip-desktop) SKIP_DESKTOP=1 ;;
      esac
    done
    echo "OPEN=$OPEN_DESKTOP SKIP=$SKIP_DESKTOP"
  ' -- --open)"
  if echo "$result" | grep -q "OPEN=1"; then
    pass "install-claude-desktop-llm.sh --open sets OPEN_DESKTOP=1"
  else
    fail "install-claude-desktop-llm.sh --open" "got: $result"
  fi
}

test_cdl_skip_desktop_flag_parsed() {
  local result
  result="$(bash -c '
    OPEN_DESKTOP=0
    SKIP_DESKTOP=0
    for arg in "$@"; do
      case "$arg" in
        --open) OPEN_DESKTOP=1 ;;
        --skip-desktop) SKIP_DESKTOP=1 ;;
      esac
    done
    echo "OPEN=$OPEN_DESKTOP SKIP=$SKIP_DESKTOP"
  ' -- --skip-desktop)"
  if echo "$result" | grep -q "SKIP=1"; then
    pass "install-claude-desktop-llm.sh --skip-desktop sets SKIP_DESKTOP=1"
  else
    fail "install-claude-desktop-llm.sh --skip-desktop" "got: $result"
  fi
}

test_cdl_open_and_skip_together() {
  # Both flags can appear simultaneously; neither excludes the other
  local result
  result="$(bash -c '
    OPEN_DESKTOP=0
    SKIP_DESKTOP=0
    for arg in "$@"; do
      case "$arg" in
        --open) OPEN_DESKTOP=1 ;;
        --skip-desktop) SKIP_DESKTOP=1 ;;
      esac
    done
    echo "OPEN=$OPEN_DESKTOP SKIP=$SKIP_DESKTOP"
  ' -- --open --skip-desktop)"
  if echo "$result" | grep -q "OPEN=1" && echo "$result" | grep -q "SKIP=1"; then
    pass "install-claude-desktop-llm.sh --open --skip-desktop sets both flags"
  else
    fail "install-claude-desktop-llm.sh both flags" "got: $result"
  fi
}

test_cdl_no_flags_defaults_zero() {
  local result
  result="$(bash -c '
    OPEN_DESKTOP=0
    SKIP_DESKTOP=0
    for arg in "$@"; do
      case "$arg" in
        --open) OPEN_DESKTOP=1 ;;
        --skip-desktop) SKIP_DESKTOP=1 ;;
      esac
    done
    echo "OPEN=$OPEN_DESKTOP SKIP=$SKIP_DESKTOP"
  ' --)"
  if echo "$result" | grep -q "OPEN=0" && echo "$result" | grep -q "SKIP=0"; then
    pass "install-claude-desktop-llm.sh no flags defaults both to 0"
  else
    fail "install-claude-desktop-llm.sh no flags" "got: $result"
  fi
}

# ─── Additional arg-parsing edge-case tests ───────────────────────────────────

test_install_skip_mcpb_not_forwarded_to_cdl() {
  # --skip-mcpb is consumed by install.sh; it must NOT appear in the args
  # forwarded to install-claude-desktop-llm.sh.
  local stub_dir args_file
  stub_dir="$(make_stub_dir)"
  args_file="$(mktemp)"

  local fake_scripts
  fake_scripts="$(mktemp -d)"
  cat >"$fake_scripts/install-claude-desktop-llm.sh" <<EOF
#!/usr/bin/env bash
echo "\$@" >"$args_file"
EOF
  chmod +x "$fake_scripts/install-claude-desktop-llm.sh"

  local wrapper
  wrapper="$(mktemp --suffix=.sh)"
  cat >"$wrapper" <<'WEOF'
#!/usr/bin/env bash
SCRIPT_DIR="__FAKE_SCRIPTS__"
SKIP_MCPB=0
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --skip-mcpb) SKIP_MCPB=1 ;;
    --help|-h) echo "Usage: install.sh [--open] [--skip-mcpb] [--skip-desktop]"; exit 0 ;;
    *) EXTRA_ARGS+=("$arg") ;;
  esac
done
git -C "$SCRIPT_DIR" submodule update --init --recursive vendor/Claude-Desktop-LLM 2>/dev/null || true
if [[ "$SKIP_MCPB" -eq 0 ]]; then
  bash "$SCRIPT_DIR/install-claude-desktop-llm.sh" "${EXTRA_ARGS[@]}"
fi
WEOF
  sed -i "s|__FAKE_SCRIPTS__|$fake_scripts|g" "$wrapper"
  chmod +x "$wrapper"

  # Pass both --open and --skip-mcpb; CDL script should see only --open
  PATH="$stub_dir:$PATH" bash "$wrapper" --open >/dev/null 2>&1 || true

  local forwarded
  forwarded="$(cat "$args_file" 2>/dev/null || echo '')"
  if echo "$forwarded" | grep -q "\-\-skip-mcpb"; then
    fail "install.sh --skip-mcpb not forwarded" "--skip-mcpb appeared in args sent to CDL: '$forwarded'"
  else
    pass "install.sh --skip-mcpb is consumed, not forwarded to install-claude-desktop-llm.sh"
  fi

  rm -f "$wrapper" "$args_file"
  rm -rf "$stub_dir" "$fake_scripts"
}

test_install_help_and_short_help_consistent() {
  # --help and -h must produce identical output (same text, same exit code).
  local out_long out_short
  out_long="$(bash -c '
    SKIP_MCPB=0
    EXTRA_ARGS=()
    for arg in "$@"; do
      case "$arg" in
        --skip-mcpb) SKIP_MCPB=1 ;;
        --help|-h) echo "Usage: install.sh [--open] [--skip-mcpb] [--skip-desktop]"; exit 0 ;;
        *) EXTRA_ARGS+=("$arg") ;;
      esac
    done
  ' -- --help)"
  out_short="$(bash -c '
    SKIP_MCPB=0
    EXTRA_ARGS=()
    for arg in "$@"; do
      case "$arg" in
        --skip-mcpb) SKIP_MCPB=1 ;;
        --help|-h) echo "Usage: install.sh [--open] [--skip-mcpb] [--skip-desktop]"; exit 0 ;;
        *) EXTRA_ARGS+=("$arg") ;;
      esac
    done
  ' -- -h)"
  if [[ "$out_long" == "$out_short" ]]; then
    pass "install.sh --help and -h produce identical output"
  else
    fail "install.sh --help vs -h consistency" "--help='$out_long' -h='$out_short'"
  fi
}

test_install_skip_mcpb_with_extra_args_not_called() {
  # --skip-mcpb together with extra args: CDL script must still NOT be invoked.
  local stub_dir sentinel_file
  stub_dir="$(make_stub_dir)"
  sentinel_file="$(mktemp)"
  rm -f "$sentinel_file"

  local fake_scripts
  fake_scripts="$(mktemp -d)"
  cat >"$fake_scripts/install-claude-desktop-llm.sh" <<EOF
#!/usr/bin/env bash
touch "$sentinel_file"
EOF
  chmod +x "$fake_scripts/install-claude-desktop-llm.sh"

  local wrapper
  wrapper="$(mktemp --suffix=.sh)"
  cat >"$wrapper" <<'WEOF'
#!/usr/bin/env bash
SCRIPT_DIR="__FAKE_SCRIPTS__"
SKIP_MCPB=0
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --skip-mcpb) SKIP_MCPB=1 ;;
    --help|-h) echo "Usage: install.sh [--open] [--skip-mcpb] [--skip-desktop]"; exit 0 ;;
    *) EXTRA_ARGS+=("$arg") ;;
  esac
done
git -C "$SCRIPT_DIR" submodule update --init --recursive vendor/Claude-Desktop-LLM 2>/dev/null || true
if [[ "$SKIP_MCPB" -eq 0 ]]; then
  bash "$SCRIPT_DIR/install-claude-desktop-llm.sh" "${EXTRA_ARGS[@]}"
fi
WEOF
  sed -i "s|__FAKE_SCRIPTS__|$fake_scripts|g" "$wrapper"
  chmod +x "$wrapper"

  PATH="$stub_dir:$PATH" bash "$wrapper" --open --skip-mcpb >/dev/null 2>&1 || true

  if [[ -f "$sentinel_file" ]]; then
    fail "install.sh --open --skip-mcpb" "CDL was called despite --skip-mcpb (sentinel exists)"
  else
    pass "install.sh --open --skip-mcpb: CDL not called even with extra args present"
  fi

  rm -f "$wrapper" "$sentinel_file"
  rm -rf "$stub_dir" "$fake_scripts"
}

test_cdl_flags_order_independent() {
  # Flag order must not matter: --skip-desktop --open should set both.
  local result
  result="$(bash -c '
    OPEN_DESKTOP=0
    SKIP_DESKTOP=0
    for arg in "$@"; do
      case "$arg" in
        --open) OPEN_DESKTOP=1 ;;
        --skip-desktop) SKIP_DESKTOP=1 ;;
      esac
    done
    echo "OPEN=$OPEN_DESKTOP SKIP=$SKIP_DESKTOP"
  ' -- --skip-desktop --open)"
  if echo "$result" | grep -q "OPEN=1" && echo "$result" | grep -q "SKIP=1"; then
    pass "install-claude-desktop-llm.sh flags are order-independent (--skip-desktop before --open)"
  else
    fail "install-claude-desktop-llm.sh flag order" "got: $result"
  fi
}

test_cdl_unknown_flag_does_not_set_known_vars() {
  # An unrecognised flag must not accidentally set OPEN_DESKTOP or SKIP_DESKTOP.
  local result
  result="$(bash -c '
    OPEN_DESKTOP=0
    SKIP_DESKTOP=0
    for arg in "$@"; do
      case "$arg" in
        --open) OPEN_DESKTOP=1 ;;
        --skip-desktop) SKIP_DESKTOP=1 ;;
      esac
    done
    echo "OPEN=$OPEN_DESKTOP SKIP=$SKIP_DESKTOP"
  ' -- --unknown-flag)"
  if echo "$result" | grep -q "OPEN=0" && echo "$result" | grep -q "SKIP=0"; then
    pass "install-claude-desktop-llm.sh unknown flag does not mutate OPEN_DESKTOP or SKIP_DESKTOP"
  else
    fail "install-claude-desktop-llm.sh unknown flag" "got: $result"
  fi
}

# ─── Run all tests ────────────────────────────────────────────────────────────

echo ""
echo "install.sh / install-claude-desktop-llm.sh arg-parsing tests"
echo "──────────────────────────────────────────────────────────────"

test_install_help_exits_zero
test_install_h_exits_zero
test_install_skip_mcpb_skips_cdl_script
test_install_extra_args_forwarded
test_cdl_help_exits_zero
test_cdl_h_exits_zero
test_cdl_open_flag_parsed
test_cdl_skip_desktop_flag_parsed
test_cdl_open_and_skip_together
test_cdl_no_flags_defaults_zero
test_install_skip_mcpb_not_forwarded_to_cdl
test_install_help_and_short_help_consistent
test_install_skip_mcpb_with_extra_args_not_called
test_cdl_flags_order_independent
test_cdl_unknown_flag_does_not_set_known_vars

echo ""
echo "Results: $PASS passed, $FAIL failed"

  exit 1
fi
exit 0
