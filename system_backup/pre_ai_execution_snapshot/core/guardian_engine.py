# BLOCO 7 — GUARDIAN 2.0
# Camada Constitucional de Integridade Operacional
# Subordinado exclusivamente ao Orchestrator

import time
from collections import defaultdict


class UnauthorizedExecutionError(Exception):
    pass


class GuardianEngine:

    def __init__(self, orchestrator_reference):
        if orchestrator_reference is None:
            raise UnauthorizedExecutionError(
                "Guardian must be instantiated only via Orchestrator"
            )

        self.orchestrator = orchestrator_reference
        self.event_counter = defaultdict(list)
        self.external_failures = defaultdict(int)

    # =====================================================
    # ENTRY POINT (EXCLUSIVO DO ORCHESTRATOR)
    # =====================================================

    def process_event(self, event: dict):

        self._validate_event_structure(event)

        issue = (
            self._detect_integrity_violation(event)
            or self._detect_loop(event)
            or self._detect_external_failure(event)
            or self._detect_structural_conflict(event)
        )

        if issue:
            severity = self._classify_severity(issue)
            return self._emit_alert(issue, severity, event)

        return None

    # =====================================================
    # VALIDAÇÃO BÁSICA
    # =====================================================

    def _validate_event_structure(self, event: dict):
        required_fields = ["event_id", "timestamp", "event_type"]

        for field in required_fields:
            if field not in event:
                raise ValueError(f"Guardian: Missing required field {field}")

    # =====================================================
    # DETECÇÕES
    # =====================================================

    def _detect_integrity_violation(self, event):

        if event.get("origin") == "direct_write_attempt":
            return "integrity_violation_direct_write"

        if event.get("state_changed_without_log"):
            return "integrity_violation_state_without_log"

        if event.get("baseline_modified_without_promotion"):
            return "integrity_violation_baseline"

        return None

    def _detect_loop(self, event):

        event_type = event["event_type"]
        now = time.time()

        self.event_counter[event_type].append(now)

        # manter apenas últimos 30 segundos
        self.event_counter[event_type] = [
            t for t in self.event_counter[event_type] if now - t <= 30
        ]

        if len(self.event_counter[event_type]) > 10:
            return "loop_detected"

        return None

    def _detect_external_failure(self, event):

        if event.get("external_failure"):
            service = event.get("external_service", "unknown")
            self.external_failures[service] += 1

            if self.external_failures[service] >= 3:
                return "external_failure_persistent"

        return None

    def _detect_structural_conflict(self, event):

        if event.get("pricing_outside_phase4"):
            return "structural_conflict_pricing_phase"

        if event.get("ads_active_in_containment"):
            return "structural_conflict_ads_macro"

        if event.get("promotion_without_stat_validation"):
            return "structural_conflict_promotion"

        return None

    # =====================================================
    # SEVERIDADE
    # =====================================================

    def _classify_severity(self, issue):

        critical = [
            "integrity_violation_direct_write",
            "integrity_violation_state_without_log",
            "integrity_violation_baseline",
            "structural_conflict_pricing_phase",
            "structural_conflict_ads_macro",
            "structural_conflict_promotion",
        ]

        if issue in critical:
            return "CRITICAL"

        if issue in ["external_failure_persistent", "loop_detected"]:
            return "WARNING"

        return "INFO"

    # =====================================================
    # EMISSÃO DE ALERTA (SEM EXECUTAR AÇÃO)
    # =====================================================

    def _emit_alert(self, issue, severity, original_event):

        alert_event = {
            "event_id": f"guardian_{int(time.time()*1000)}",
            "timestamp": time.time(),
            "event_type": "guardian_alert_emitted",
            "severity": severity,
            "issue_type": issue,
            "origin_engine": original_event.get("origin_engine"),
            "product_id": original_event.get("product_id"),
            "metric_context": original_event.get("metric_context"),
            "system_version": original_event.get("system_version"),
        }

        # Guardian não altera state
        # Apenas solicita persistência via Orchestrator
        self.orchestrator.persist_event(alert_event)

        return alert_event
