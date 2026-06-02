from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


class LegalKnowledgeBase:
    """Loads ClauseGuide's curated legal-risk KB from JSON files."""

    def __init__(self, root: Path | None = None) -> None:
        backend_root = Path(__file__).resolve().parents[2]
        self.root = root or backend_root / "legal-risk-kb"
        self._playbooks = self._load_playbooks()
        self._risk_rules = self._load_risk_rules()
        self._aliases = self._load_json(self.root / "clause-taxonomy" / "custom_clause_aliases.json", default={})
        self._cuad_aliases = self._load_json(self.root / "clause-taxonomy" / "cuad_derived_aliases.json", default={})
        self._cuad_index = self._load_json(
            self.root / "source-data" / "cuad_v1" / "derived" / "cuad_clause_index.json",
            default={"metadata": {}, "labels": []},
        )
        self._india_notes = self._load_json(self.root / "jurisdiction-india" / "india_legal_notes.json", default={})
        self._benchmarks = self._load_json(self.root / "standard-templates" / "benchmark_summaries.json", default={})
        self._cuad_by_internal = self._group_cuad_labels()

    def playbook(self, contract_type: str) -> dict[str, Any]:
        return dict(self._playbooks.get(contract_type, {}))

    def expected_clauses(self, contract_type: str) -> list[str]:
        playbook = self.playbook(contract_type)
        return [str(item.get("clause")) for item in playbook.get("expected_clauses", []) if item.get("clause")]

    def recommended_clauses(self, contract_type: str) -> list[str]:
        playbook = self.playbook(contract_type)
        return [str(item) for item in playbook.get("recommended_clauses", [])]

    def missing_clause_profile(self, contract_type: str, clause_type: str) -> dict[str, Any]:
        playbook = self.playbook(contract_type)
        for item in playbook.get("expected_clauses", []):
            if item.get("clause") == clause_type:
                return dict(item)
        return {}

    def aliases_for(self, clause_type: str) -> list[str]:
        aliases = set(str(item) for item in self._aliases.get(clause_type, []))
        aliases.update(str(item) for item in self._cuad_aliases.get(clause_type, []))
        return sorted(aliases)

    def cuad_metadata(self) -> dict[str, Any]:
        return dict(self._cuad_index.get("metadata", {}))

    def cuad_labels_for(self, clause_type: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self._cuad_by_internal.get(clause_type, [])]

    def cuad_examples_for(self, clause_type: str, *, limit: int = 8) -> list[str]:
        examples: list[str] = []
        for label in self._cuad_by_internal.get(clause_type, []):
            for answer in label.get("representative_answers", []):
                text = str(answer)
                if text and text not in examples:
                    examples.append(text)
                if len(examples) >= limit:
                    return examples
        return examples

    def cuad_reference_text_for(self, clause_type: str, *, example_limit: int = 4) -> str:
        labels = self.cuad_labels_for(clause_type)
        if not labels:
            return ""
        label_names = ", ".join(str(item.get("cuad_label", "")) for item in labels[:5])
        examples = " ".join(self.cuad_examples_for(clause_type, limit=example_limit))
        return f"CUAD labels: {label_names}. CUAD examples: {examples}".strip()

    def risk_rules_for(self, contract_type: str, clause_type: str) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        for rule in self._risk_rules:
            document_types = set(str(item) for item in rule.get("document_types", []))
            if document_types and contract_type not in document_types:
                continue
            if str(rule.get("clause")) != clause_type:
                continue
            rules.append(rule)
        return rules

    def false_positive_guardrails(self, contract_type: str) -> list[str]:
        playbook = self.playbook(contract_type)
        return [str(item) for item in playbook.get("false_positive_guardrails", [])]

    def review_focus(self, contract_type: str) -> list[str]:
        playbook = self.playbook(contract_type)
        return [str(item) for item in playbook.get("review_focus", [])]

    def jurisdiction_warnings(self, *, contract_type: str, present_clause_types: set[str], full_text: str) -> list[dict[str, str]]:
        notes = self._india_notes.get("notes", [])
        lowered = full_text.lower()
        output: list[dict[str, str]] = []
        for note in notes:
            applies_to = set(str(item) for item in note.get("applies_to", []))
            if contract_type not in applies_to and not applies_to.intersection(present_clause_types):
                continue
            triggers = [str(item).lower() for item in note.get("risk_triggers", [])]
            if triggers and not any(trigger in lowered for trigger in triggers):
                continue
            output.append(
                {
                    "id": str(note.get("id", "")),
                    "warning": str(note.get("warning", "")),
                    "recommended_check": str(note.get("recommended_check", "")),
                }
            )
        return output

    def benchmark_notes(self, contract_type: str) -> list[dict[str, Any]]:
        benchmarks = self._benchmarks.get("benchmarks", [])
        output: list[dict[str, Any]] = []
        for benchmark in benchmarks:
            if contract_type in set(str(item) for item in benchmark.get("document_types", [])):
                output.append(dict(benchmark))
        return output

    def _load_playbooks(self) -> dict[str, dict[str, Any]]:
        directory = self.root / "document-type-playbooks"
        playbooks: dict[str, dict[str, Any]] = {}
        if not directory.exists():
            return playbooks
        for path in sorted(directory.glob("*.json")):
            payload = self._load_json(path, default={})
            document_type = payload.get("document_type")
            if document_type:
                playbooks[str(document_type)] = payload
        return playbooks

    def _load_risk_rules(self) -> list[dict[str, Any]]:
        directory = self.root / "risk-rules"
        rules: list[dict[str, Any]] = []
        if not directory.exists():
            return rules
        for path in sorted(directory.glob("*.json")):
            payload = self._load_json(path, default={})
            for rule in payload.get("rules", []):
                if rule.get("id") and rule.get("clause"):
                    rules.append(dict(rule))
        return rules

    def _group_cuad_labels(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for label in self._cuad_index.get("labels", []):
            internal = str(label.get("internal_clause", ""))
            if not internal:
                continue
            grouped.setdefault(internal, []).append(dict(label))
        for labels in grouped.values():
            labels.sort(key=lambda item: int(item.get("positive_answer_count", 0)), reverse=True)
        return grouped

    @staticmethod
    def _load_json(path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def get_legal_kb() -> LegalKnowledgeBase:
    return LegalKnowledgeBase()
