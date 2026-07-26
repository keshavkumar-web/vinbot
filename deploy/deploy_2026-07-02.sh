#!/usr/bin/env bash
# =============================================================================
#  UHBVN Assistant — Production deployment: 2026-07-02 release
# =============================================================================
#  Applies ALL of today's (2026-07-02) updates:
#    1. Customer UAT fixes — figure recall (security deposit → Rs.750/KW,
#       meter fee → Rs.100/200/750/1500), back-reference follow-ups
#       ("how many of those…"), de-jargoned clarify wording. (TOP_K 5→8)
#    2. Superlative / argmax — "which circle has the most/least/highest X?"
#       ranked deterministically over SQLite (aggregates/zones excluded).
#    3. RTS Act ingested — designated officer per service (shifting → JE,
#       new connection/change/reduction → SDO); structured labelled rows so the
#       officer column can't be mis-read. Requires running add_rts_act.py HERE
#       (prod's knowledge base differs from dev's — never copy the pkl across).
#    4. Segregation / breakup — "segregation on connection type", "breakup",
#       "category-wise", "split", "bifurcation" now return EVERY category column
#       (Domestic, LT NDS, HT Industry, …) instead of repeating the Total. Also a
#       follow-up: after "total connection count", "segregation on connection
#       type" gives the full split. Deterministic (all columns except Total).
#    5. Organisation identity — "what is UHBVN?" / full-form questions answer
#       (Uttar Haryana Bijli Vitran Nigam) instead of "could not find"; specific
#       figures/officers still require grounding.
#    6. Row-wise breakdown — "circle wise number of connections" (also district/
#       region wise, "each circle", "zone wise") lists EVERY circle's value
#       (Karnal 543,445 … Panchkula 195,820) instead of collapsing to the Grand
#       Total. Deterministic (rows from SQLite).
#    7. Unknown-place safety — "connections in Mumbai as of March 2026" no longer
#       serves the Grand Total (a trailing month used to defeat the guard); an
#       unrecognised city now clarifies. Correctness fix (never serve a wrong row).
#    9. Abbreviations glossaries ingested — Haryana_DISCOM_Abbreviations.txt (255
#       entries: UHBVN/DHBVN, RTS, FGRA/SGRA, APPC, MGJGY, FPO, DMRC, SDO/XEN/JE, …)
#       AND Electricity_Department_Abbreviations.txt (146 entries: POSOCO, PGCIL,
#       SAIFI/SAIDI, DT/DT Failure Rate, UDAY, PRAAPTI, IEX, …) so "what is X /
#       full form of X" answers. Requires running add_abbreviations.py AND
#       add_electricity_abbrev.py HERE (prod pkl differs from dev's). The two
#       glossaries don't conflict (see step 3); figures still come from SQLite only.
#    8. Deterministic conversational slots (+2nd-round hardening) — follow-ups keep
#       the active dataset/entity/metric and change only the named dimension
#       ("Total?", "Zone-I?", "Load?", "Breakup?"). Hardened after UAT: bare
#       "Domestic?" picks Domestic (not Bulk Supply Domestic); "Zone-I total"
#       resolves Zone-I; dataset switches ("damaged transformers", "total connected
#       load") route correctly; row-wise honours the named metric; superlative by an
#       explicit category; bare "Difference?" computes; and — SAFETY — an unknown
#       place ("connections on moon") never inherits a stale row (it refuses).
#
#  Prereqs on the server: uhbvn.service exists; /opt/uhbvn owned by 'uhbvn';
#  backend/.venv present; OPENAI_API_KEY in backend/.env (chmod 600, uhbvn).
#  Run as a sudo user (e.g. ecadmin). No new pip deps; no frontend rebuild.
#
#  Usage (on the server):
#     scp uhbvn_deploy_2026-07-02.tar.gz ecadmin@<SERVER>:/tmp/      # from dev box first
#     bash deploy_2026-07-02.sh [/path/to/uhbvn_deploy_2026-07-02.tar.gz]
# =============================================================================
set -euo pipefail

APP=/opt/uhbvn
SVC=uhbvn
RUNUSER=uhbvn
HEALTH_URL="http://192.168.36.51:8000/api/health"      # unit binds the LAN IP, not localhost
TARBALL="${1:-/tmp/uhbvn_deploy_2026-07-02.tar.gz}"
STAMP="$(date +%F_%H%M%S)"

echo "==> UHBVN 2026-07-02 deploy"
echo "    tarball : $TARBALL"
echo "    target  : $APP   service: $SVC   run-as: $RUNUSER"
[ -f "$TARBALL" ] || { echo "!! Tarball not found: $TARBALL"; exit 1; }

echo "==> 1/6  Snapshot current app (rollback point: app.bak.$STAMP)"
sudo -u "$RUNUSER" cp -a "$APP/backend/app" "$APP/backend/app.bak.$STAMP"

echo "==> 2/6  Extract update into $APP  (relative paths -> backend/...)"
sudo -u "$RUNUSER" tar -xzf "$TARBALL" -C "$APP"
sudo -u "$RUNUSER" find "$APP/backend/app" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

echo "==> 3/6  Ingest RTS Act + abbreviations glossaries into the KB (idempotent; backs up pkl)"
sudo -u "$RUNUSER" bash -c "cd '$APP/backend' && .venv/bin/python add_rts_act.py"
sudo -u "$RUNUSER" bash -c "cd '$APP/backend' && .venv/bin/python add_abbreviations.py"
sudo -u "$RUNUSER" bash -c "cd '$APP/backend' && .venv/bin/python add_electricity_abbrev.py"

echo "==> 4/6  Restart service"
sudo systemctl restart "$SVC"
sleep 3
if systemctl is-active --quiet "$SVC"; then
  echo "    $SVC is active (running)"
else
  echo "!! $SVC did NOT start — check: sudo journalctl -u $SVC -e"
  echo "   Rollback: sudo -u $RUNUSER bash -c 'cd $APP/backend && rm -rf app && mv app.bak.$STAMP app' && sudo systemctl restart $SVC"
  exit 1
fi

echo "==> 5/6  Health check ($HEALTH_URL)"
curl -fsS "$HEALTH_URL" && echo || echo "   (health check failed — verify manually)"

echo "==> 6/6  Post-deploy gate (informational; review before sign-off)"
set +e
sudo -u "$RUNUSER" bash -c "cd '$APP/backend' && \
  echo -n '   eval_tables    : ' && .venv/bin/python eval_tables.py | tail -1 && \
  echo -n '   eval_rag       : ' && .venv/bin/python eval_rag.py | tail -1 && \
  echo -n '   eval_followup  : ' && .venv/bin/python eval_followup.py | tail -1 && \
  echo    '   validate_e2e   :' && .venv/bin/python validate_e2e.py | tail -3"
set -e

echo ""
echo "==> DONE.  Expected gate: eval_tables 27/27, eval_rag 7/7, eval_followup 26/26, validate_e2e ALL GREEN (0% FP)."
echo "    Spot-check via API:"
echo "      SID=\$(curl -s -XPOST https://uhbvn.vinbox.in/api/session | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"session_id\"])')"
echo "      curl -s -XPOST https://uhbvn.vinbox.in/api/chat -H 'Content-Type: application/json' -d \"{\\\"session_id\\\":\\\"\$SID\\\",\\\"message\\\":\\\"who is the designated officer for shifting of meter?\\\"}\"   # -> JE (In charge)"
echo "      # segregation (same SID, after a 'total connection count' turn):"
echo "      curl -s -XPOST https://uhbvn.vinbox.in/api/chat -H 'Content-Type: application/json' -d \"{\\\"session_id\\\":\\\"\$SID\\\",\\\"message\\\":\\\"segregation on connection type\\\"}\"   # -> Domestic 3,003,464, LT NDS 449,105, … (NOT the Total 3,892,250)"
echo "      # circle-wise breakdown:"
echo "      curl -s -XPOST https://uhbvn.vinbox.in/api/chat -H 'Content-Type: application/json' -d \"{\\\"session_id\\\":\\\"\$SID\\\",\\\"message\\\":\\\"circle wise number of connections\\\"}\"   # -> Karnal 543,445 … Panchkula 195,820 (each circle, not the Grand Total)"
echo "      # unknown-place safety:"
echo "      curl -s -XPOST https://uhbvn.vinbox.in/api/chat -H 'Content-Type: application/json' -d \"{\\\"session_id\\\":\\\"\$SID\\\",\\\"message\\\":\\\"connections in Mumbai as of march 2026\\\"}\"   # -> clarify (NOT the Grand Total)"
echo "      # abbreviations glossary:"
echo "      curl -s -XPOST https://uhbvn.vinbox.in/api/chat -H 'Content-Type: application/json' -d \"{\\\"session_id\\\":\\\"\$SID\\\",\\\"message\\\":\\\"what is the full form of RTS?\\\"}\"   # -> Right to Service (Haryana Right to Service Act, 2014)"
echo ""
echo "    ROLLBACK if needed:"
echo "      sudo -u $RUNUSER bash -c 'cd $APP/backend && rm -rf app && mv app.bak.$STAMP app'"
echo "      sudo systemctl restart $SVC"
echo "      # (RTS chunks: the KB was backed up to backend/knowledge_db.pkl.bak)"
