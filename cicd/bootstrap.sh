#!/usr/bin/env bash
#
# bootstrap.sh — Idempotent Jenkins-server provisioning for VinBot CI/CD.
#
# Target: a FRESH Ubuntu 22.04 LTS host that will run ONLY Jenkins.
# Safe to re-run: every check/install step first verifies whether the
# component is already present (and at a sufficient version) and skips it
# if so. Nothing already installed is ever reinstalled or restarted
# unnecessarily.
#
# Usage:
#   sudo ./bootstrap.sh
#
# Full run output is also written to /var/log/vinbot-bootstrap.log.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  readonly C_RESET='\033[0m' C_GREEN='\033[0;32m' C_YELLOW='\033[0;33m' \
           C_RED='\033[0;31m' C_BLUE='\033[0;34m'
else
  readonly C_RESET='' C_GREEN='' C_YELLOW='' C_RED='' C_BLUE=''
fi

readonly LOG_FILE="/var/log/vinbot-bootstrap.log"
readonly REQUIRED_JAVA_MAJOR=17

_ts() { date '+%Y-%m-%d %H:%M:%S'; }

log_info()    { printf "[%s] %b[i]%b %s\n"  "$(_ts)" "$C_BLUE"   "$C_RESET" "$1"; }
log_success() { printf "[%s] %b\xe2\x9c\x93%b %s\n" "$(_ts)" "$C_GREEN"  "$C_RESET" "$1"; }
log_warn()    { printf "[%s] %b\xe2\x9a\xa0%b %s\n" "$(_ts)" "$C_YELLOW" "$C_RESET" "$1" >&2; }
log_error()   { printf "[%s] %b\xe2\x9c\x97%b %s\n" "$(_ts)" "$C_RED"    "$C_RESET" "$1" >&2; }

trap 'log_error "bootstrap failed at line $LINENO (exit code $?). See ${LOG_FILE} for full output."' ERR

# Every subsequent line of stdout/stderr is mirrored into $LOG_FILE, in
# addition to still printing to the console.
setup_logging() {
  touch "$LOG_FILE" 2>/dev/null || { log_error "Cannot write to ${LOG_FILE} (run as root?)"; exit 1; }
  chmod 0644 "$LOG_FILE"
  exec > >(tee -a "$LOG_FILE") 2>&1
  log_info "=== VinBot Jenkins bootstrap started (log: ${LOG_FILE}) ==="
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    log_error "This script must be run as root (use: sudo ./bootstrap.sh)"
    exit 1
  fi
}

# Generic retry wrapper: retry <max_attempts> <command...>
# Used for anything that talks to the network (apt, curl) so a transient
# blip doesn't fail the whole bootstrap.
retry() {
  local max_attempts="$1"; shift
  local attempt=1
  until "$@"; do
    if (( attempt >= max_attempts )); then
      return 1
    fi
    log_warn "Attempt ${attempt}/${max_attempts} failed: $* — retrying in $((attempt * 2))s..."
    sleep $((attempt * 2))
    ((attempt++))
  done
}

_internet_checked=0
check_internet() {
  if [[ "${_internet_checked}" -eq 1 ]]; then
    return
  fi
  log_info "Checking internet connectivity..."
  if retry 3 curl -fsS --max-time 5 -o /dev/null "http://archive.ubuntu.com"; then
    log_success "Internet connectivity OK (archive.ubuntu.com reachable)"
    _internet_checked=1
  else
    log_error "No internet connectivity to archive.ubuntu.com after 3 attempts."
    log_error "Check network/DNS/proxy settings, then re-run this script."
    exit 1
  fi
}

# apt-get update is expensive-ish and unnecessary on a no-op re-run, so it is
# only ever invoked lazily, the first time an install actually happens.
_apt_updated=0
apt_update_now() {
  log_info "Refreshing apt package index..."
  if ! retry 3 apt-get update -qq; then
    log_error "apt-get update failed after 3 attempts — check apt sources / network / proxy."
    log_error "Try manually: sudo apt-get update"
    exit 1
  fi
  _apt_updated=1
}

ensure_apt_updated() {
  if [[ "${_apt_updated}" -eq 0 ]]; then
    check_internet
    apt_update_now
  fi
}

# apt_install <package> — idempotent, retried, verified install.
apt_install() {
  local pkg="$1"
  if dpkg -s "$pkg" >/dev/null 2>&1; then
    return 0
  fi
  ensure_apt_updated
  log_info "Installing package: ${pkg}..."
  if ! retry 3 apt-get install -y -qq "$pkg"; then
    log_error "Failed to install package '${pkg}' after 3 attempts."
    log_error "Try manually: sudo apt-get install ${pkg}"
    exit 1
  fi
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    log_error "Package '${pkg}' install reported success but dpkg does not show it registered — aborting."
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# OS / host detection
# ---------------------------------------------------------------------------
detect_os() {
  if [[ ! -f /etc/os-release ]]; then
    log_error "/etc/os-release not found — cannot verify this is Ubuntu."
    exit 1
  fi
  # shellcheck source=/dev/null
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" ]]; then
    log_error "This script targets Ubuntu only (detected: ${ID:-unknown})."
    exit 1
  fi
  if [[ "${VERSION_ID:-}" != "22.04" ]]; then
    log_warn "This script was written for Ubuntu 22.04; detected ${VERSION_ID:-unknown}. Continuing anyway."
  fi
}

detect_system_info() {
  local kernel arch dpkg_arch mem_total mem_avail disk_total disk_avail

  kernel="$(uname -r)"
  arch="$(uname -m)"
  dpkg_arch="$(dpkg --print-architecture 2>/dev/null || echo unknown)"
  mem_total="$(free -h | awk '/^Mem:/ {print $2}')"
  mem_avail="$(free -h | awk '/^Mem:/ {print $7}')"
  disk_total="$(df -h / | awk 'NR==2 {print $2}')"
  disk_avail="$(df -h / | awk 'NR==2 {print $4}')"

  log_info "---- Host details ----"
  log_info "Ubuntu version:   ${PRETTY_NAME}"
  log_info "Kernel version:   ${kernel}"
  log_info "CPU architecture: ${arch} (dpkg: ${dpkg_arch})"
  log_info "RAM:              ${mem_avail} available of ${mem_total}"
  log_info "Disk (/):         ${disk_avail} available of ${disk_total}"
  log_info "-----------------------"
}

# ---------------------------------------------------------------------------
# Component checks — each is: already present at a sufficient version?
# report and skip : install (or upgrade) and re-verify.
# ---------------------------------------------------------------------------

# Extracts the major version number from `java -version`'s first line,
# handling both the old "1.8.0_392" scheme and the modern "17.0.9" scheme.
_java_major_version() {
  local raw major
  raw="$(java -version 2>&1 | head -n1)"
  major="$(grep -oP '"\K[0-9]+' <<<"$raw" || true)"
  if [[ "$major" == "1" ]]; then
    major="$(grep -oP '"1\.\K[0-9]+' <<<"$raw" || true)"
  fi
  echo "$major"
}

check_java() {
  if command -v java >/dev/null 2>&1; then
    local ver_str major
    ver_str="$(java -version 2>&1 | head -n1)"
    major="$(_java_major_version)"
    if [[ -n "$major" ]] && (( major >= REQUIRED_JAVA_MAJOR )); then
      log_success "Java already installed: ${ver_str} (meets requirement >= ${REQUIRED_JAVA_MAJOR})"
      return
    fi
    log_warn "Java found (${ver_str}) but version ${major:-unknown} < required ${REQUIRED_JAVA_MAJOR}. Installing OpenJDK ${REQUIRED_JAVA_MAJOR}..."
  else
    log_info "Java not found. Installing OpenJDK ${REQUIRED_JAVA_MAJOR} (required by current Jenkins LTS)..."
  fi
  apt_install openjdk-17-jdk-headless
  command -v java >/dev/null 2>&1 || { log_error "Java install failed."; exit 1; }
  local new_major
  new_major="$(_java_major_version)"
  if [[ -z "$new_major" ]] || (( new_major < REQUIRED_JAVA_MAJOR )); then
    log_error "Java installed but reported version (${new_major:-unknown}) still below ${REQUIRED_JAVA_MAJOR}."
    log_error "Another JDK may be taking precedence — check: sudo update-alternatives --config java"
    exit 1
  fi
  log_success "Java installed: $(java -version 2>&1 | head -n1)"
}

check_git() {
  if command -v git >/dev/null 2>&1; then
    log_success "Git already installed (version $(git --version | awk '{print $3}'))"
    return
  fi
  log_info "Installing Git..."
  apt_install git
  command -v git >/dev/null 2>&1 || { log_error "Git install failed."; exit 1; }
  log_success "Git installed (version $(git --version | awk '{print $3}'))"
}

check_curl() {
  if command -v curl >/dev/null 2>&1; then
    log_success "curl already installed (version $(curl --version | head -n1 | awk '{print $2}'))"
    return
  fi
  log_info "Installing curl..."
  apt_install curl
  command -v curl >/dev/null 2>&1 || { log_error "curl install failed."; exit 1; }
  log_success "curl installed (version $(curl --version | head -n1 | awk '{print $2}'))"
}

# The Jenkins server needs an SSH CLIENT to push deployments to the dev app
# server over SSH; it does not need an SSH SERVER of its own for this
# pipeline (any existing sshd used for your own admin access is left alone).
check_ssh_client() {
  if command -v ssh >/dev/null 2>&1; then
    log_success "OpenSSH client already installed (version $(ssh -V 2>&1 | awk '{print $1}'))"
    return
  fi
  log_info "Installing OpenSSH client..."
  apt_install openssh-client
  command -v ssh >/dev/null 2>&1 || { log_error "OpenSSH client install failed."; exit 1; }
  log_success "OpenSSH client installed (version $(ssh -V 2>&1 | awk '{print $1}'))"
}

download_jenkins_key() {
  local key_url="https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key"
  local key_path="/usr/share/keyrings/jenkins-keyring.asc"
  install -d -m 0755 /usr/share/keyrings
  log_info "Downloading Jenkins repository key..."
  check_internet
  if ! retry 3 curl -fsSL --max-time 10 "$key_url" -o "$key_path"; then
    log_error "Failed to download Jenkins repository key from ${key_url} after 3 attempts."
    exit 1
  fi
  if [[ ! -s "$key_path" ]]; then
    log_error "Jenkins repository key file is empty after download — aborting."
    exit 1
  fi
  log_success "Jenkins repository key downloaded to ${key_path}"
}

check_jenkins() {
  if dpkg -s jenkins >/dev/null 2>&1; then
    log_success "Jenkins already installed (package version $(dpkg-query -W -f='${Version}' jenkins))"
  else
    log_info "Installing Jenkins..."
    download_jenkins_key
    echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc]" \
      "https://pkg.jenkins.io/debian-stable binary/" \
      > /etc/apt/sources.list.d/jenkins.list
    apt_update_now   # re-run: the new jenkins.list source must be indexed
    if ! retry 3 apt-get install -y -qq jenkins; then
      log_error "Failed to install the 'jenkins' package after 3 attempts."
      log_error "Try manually: sudo apt-get install jenkins"
      exit 1
    fi
    dpkg -s jenkins >/dev/null 2>&1 || { log_error "Jenkins install failed."; exit 1; }
    log_success "Jenkins package installed (version $(dpkg-query -W -f='${Version}' jenkins))"
  fi

  systemctl enable --quiet jenkins 2>/dev/null || true
  if systemctl is-active --quiet jenkins; then
    log_success "Jenkins service already running"
  else
    log_info "Starting Jenkins service..."
    systemctl start jenkins
  fi

  log_info "Waiting for Jenkins to respond on :8080 (up to 60s)..."
  local waited=0
  until curl -fsS -o /dev/null "http://localhost:8080/login"; do
    sleep 3
    waited=$((waited + 3))
    if [[ "${waited}" -ge 60 ]]; then
      log_error "Jenkins did not respond on :8080 within 60s."
      log_error "Check status with: systemctl status jenkins && journalctl -u jenkins -n 100"
      exit 1
    fi
  done
  log_success "Jenkins started successfully"
}

# Best-effort: open 8080/tcp if ufw is installed and active. Never installs
# or enables ufw itself — only adjusts it if the admin already uses it.
maybe_open_firewall() {
  if ! command -v ufw >/dev/null 2>&1; then
    return
  fi
  if ufw status | grep -q "Status: active"; then
    if ufw status | grep -q "8080"; then
      log_success "ufw already allows port 8080"
    else
      log_info "ufw is active — allowing port 8080/tcp for Jenkins..."
      ufw allow 8080/tcp
      log_success "ufw rule added for 8080/tcp"
    fi
  fi
}

print_summary() {
  local jenkins_pkg_version jenkins_hdr_version jenkins_version java_version \
        git_version jenkins_status jenkins_ip

  jenkins_pkg_version="$(dpkg-query -W -f='${Version}' jenkins 2>/dev/null || echo unknown)"
  jenkins_hdr_version="$(curl -fsS -D- -o /dev/null "http://localhost:8080/login" 2>/dev/null \
    | grep -i '^X-Jenkins:' | awk '{print $2}' | tr -d '\r' || true)"
  jenkins_version="${jenkins_hdr_version:-$jenkins_pkg_version}"

  java_version="$(java -version 2>&1 | head -n1)"
  git_version="$(git --version)"
  jenkins_status="$(systemctl is-active jenkins 2>/dev/null || echo unknown)"
  jenkins_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -z "$jenkins_ip" ]] && jenkins_ip="localhost"

  echo
  echo "================= VinBot Jenkins Bootstrap — Summary ================="
  printf "  %-24s %s\n" "Jenkins version:"        "${jenkins_version}"
  printf "  %-24s %s\n" "Java version:"            "${java_version}"
  printf "  %-24s %s\n" "Git version:"             "${git_version}"
  printf "  %-24s %s\n" "Jenkins service status:"  "${jenkins_status}"
  printf "  %-24s %s\n" "Jenkins URL:"              "http://${jenkins_ip}:8080"
  printf "  %-24s %s\n" "Initial admin password:"   "sudo cat /var/lib/jenkins/secrets/initialAdminPassword"
  printf "  %-24s %s\n" "Full bootstrap log:"        "${LOG_FILE}"
  echo "========================================================================"
  echo
  log_info "Next: open the Jenkins URL above and complete the setup wizard (Step 2)."
}

main() {
  require_root
  setup_logging
  detect_os
  detect_system_info
  check_java
  check_git
  check_curl
  check_ssh_client
  check_jenkins
  maybe_open_firewall
  print_summary
}

main "$@"
