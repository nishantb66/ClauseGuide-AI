from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
KB_ROOT = BACKEND_ROOT / "legal-risk-kb"
CUAD_SOURCE = KB_ROOT / "source-data" / "cuad_v1" / "CUAD_v1.json"
DERIVED_DIR = KB_ROOT / "source-data" / "cuad_v1" / "derived"


CUAD_TO_INTERNAL: dict[str, str] = {
    "Affiliate License-Licensee": "license",
    "Affiliate License-Licensor": "license",
    "Agreement Date": "effective_date",
    "Anti-Assignment": "assignment",
    "Audit Rights": "audit_rights",
    "Cap On Liability": "liability",
    "Change Of Control": "assignment",
    "Competitive Restriction Exception": "non_compete",
    "Covenant Not To Sue": "liability",
    "Document Name": "document_title",
    "Effective Date": "effective_date",
    "Exclusivity": "exclusivity",
    "Expiration Date": "termination",
    "Governing Law": "jurisdiction",
    "Insurance": "liability",
    "Ip Ownership Assignment": "ip_rights",
    "Irrevocable Or Perpetual License": "license",
    "Joint Ip Ownership": "ip_rights",
    "License Grant": "license",
    "Liquidated Damages": "penalty",
    "Minimum Commitment": "payment",
    "Most Favored Nation": "pricing_parity",
    "No-Solicit Of Customers": "non_solicitation",
    "No-Solicit Of Employees": "non_solicitation",
    "Non-Compete": "non_compete",
    "Non-Disparagement": "non_disparagement",
    "Non-Transferable License": "license",
    "Notice Period To Terminate Renewal": "notice_period",
    "Parties": "parties",
    "Post-Termination Services": "termination",
    "Price Restrictions": "payment",
    "Renewal Term": "auto_renewal",
    "Revenue/Profit Sharing": "payment",
    "Rofr/Rofo/Rofn": "transfer_restrictions",
    "Source Code Escrow": "software_escrow",
    "Termination For Convenience": "termination",
    "Third Party Beneficiary": "third_party_rights",
    "Uncapped Liability": "liability",
    "Unlimited/All-You-Can-Eat-License": "license",
    "Volume Restriction": "performance_obligations",
    "Warranty Duration": "warranty",
}

EXTRA_ALIASES: dict[str, list[str]] = {
    "Anti-Assignment": ["anti assignment", "may not assign", "assignment requires consent"],
    "Audit Rights": ["audit rights", "inspect records", "books and records"],
    "Cap On Liability": ["cap on liability", "liability cap", "aggregate liability"],
    "Change Of Control": ["change of control", "merger", "acquisition"],
    "Governing Law": ["governing law", "laws of", "jurisdiction"],
    "Ip Ownership Assignment": ["ip ownership", "intellectual property assignment", "work product"],
    "License Grant": ["license grant", "licensed", "permitted use"],
    "Liquidated Damages": ["liquidated damages", "penalty", "damages"],
    "Minimum Commitment": ["minimum commitment", "minimum purchase", "minimum fee"],
    "Non-Compete": ["non-compete", "compete", "competitor"],
    "Notice Period To Terminate Renewal": ["notice period", "notice to terminate renewal", "prior notice"],
    "Post-Termination Services": ["post-termination", "transition services", "after termination"],
    "Renewal Term": ["renewal term", "automatic renewal", "renew"],
    "Revenue/Profit Sharing": ["revenue sharing", "profit sharing", "royalty"],
    "Termination For Convenience": ["termination for convenience", "terminate without cause"],
    "Uncapped Liability": ["uncapped liability", "unlimited liability", "without limitation"],
    "Warranty Duration": ["warranty period", "warranty duration"],
}

STOPWORDS = {
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "by",
    "with",
    "a",
    "an",
    "any",
    "this",
    "that",
    "shall",
    "will",
    "may",
    "be",
    "is",
    "are",
    "as",
    "on",
    "from",
    "under",
    "such",
    "its",
    "it",
    "not",
}


@dataclass(slots=True)
class LabelStats:
    document_count: int = 0
    positive_answer_count: int = 0
    question: str = ""
    examples: list[str] | None = None
    term_counter: Counter[str] | None = None


def main() -> None:
    if not CUAD_SOURCE.exists():
        raise SystemExit(f"CUAD source JSON not found: {CUAD_SOURCE}")

    payload = json.loads(CUAD_SOURCE.read_text(encoding="utf-8"))
    docs = payload["data"]
    stats: dict[str, LabelStats] = defaultdict(lambda: LabelStats(examples=[], term_counter=Counter()))
    titles: list[str] = []

    for doc in docs:
        title = str(doc.get("title", ""))
        if title:
            titles.append(title)
        for paragraph in doc.get("paragraphs", []):
            for qa in paragraph.get("qas", []):
                label = _label_from_id(str(qa["id"]))
                item = stats[label]
                item.document_count += 1
                item.question = item.question or str(qa.get("question", ""))
                answers = qa.get("answers") or []
                item.positive_answer_count += len(answers)
                for answer in answers:
                    text = _normalize_text(str(answer.get("text", "")))
                    if not text:
                        continue
                    _add_example(item.examples, text)
                    item.term_counter.update(_terms(text))

    labels = []
    aliases_by_internal: dict[str, set[str]] = defaultdict(set)
    for label in sorted(stats):
        item = stats[label]
        internal = CUAD_TO_INTERNAL.get(label, _slug(label))
        aliases = sorted(set(_label_aliases(label)) | set(EXTRA_ALIASES.get(label, [])))
        for alias in aliases:
            aliases_by_internal[internal].add(alias)
        for term, count in item.term_counter.most_common(16):
            if count >= 3 and len(term) > 3:
                aliases_by_internal[internal].add(term)

        labels.append(
            {
                "cuad_label": label,
                "internal_clause": internal,
                "question": item.question,
                "document_count": item.document_count,
                "positive_answer_count": item.positive_answer_count,
                "aliases": aliases,
                "top_terms": [term for term, count in item.term_counter.most_common(20) if count >= 3],
                "representative_answers": item.examples[:12],
            }
        )

    metadata = {
        "source": "theatticusproject/cuad",
        "source_url": "https://huggingface.co/datasets/theatticusproject/cuad",
        "atticus_url": "https://www.atticusprojectai.org/cuad/",
        "license": "CC BY 4.0",
        "source_file": "CUAD_v1/CUAD_v1.json",
        "contract_count": len(docs),
        "cuad_label_count": len(labels),
        "positive_answer_count": sum(item["positive_answer_count"] for item in labels),
    }
    index = {"metadata": metadata, "labels": labels}

    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(DERIVED_DIR / "cuad_clause_index.json", index)
    _write_json(
        DERIVED_DIR / "cuad_contract_titles.json",
        {"metadata": metadata, "titles": sorted(titles)},
    )
    _write_json(
        KB_ROOT / "clause-taxonomy" / "cuad_clause_types.json",
        {
            "source_note": (
                "Actual CUAD v1 label index derived from the official theatticusproject/cuad "
                "dataset. Runtime uses compact metadata/examples instead of loading full contracts."
            ),
            "metadata": metadata,
            "clause_types": [
                {
                    "id": _slug(item["cuad_label"]),
                    "label": item["cuad_label"],
                    "maps_to": item["internal_clause"],
                    "positive_answer_count": item["positive_answer_count"],
                    "document_count": item["document_count"],
                    "aliases": item["aliases"],
                }
                for item in labels
            ],
        },
    )
    _write_json(
        KB_ROOT / "clause-taxonomy" / "cuad_derived_aliases.json",
        {
            clause_type: sorted(values)
            for clause_type, values in sorted(aliases_by_internal.items())
            if clause_type not in {"document_title", "parties", "effective_date"}
        },
    )
    _write_json(KB_ROOT / "source-data" / "cuad_v1" / "attribution.json", metadata)
    print(
        f"Generated CUAD KB: {metadata['contract_count']} contracts, "
        f"{metadata['cuad_label_count']} labels, {metadata['positive_answer_count']} positive answers"
    )


def _label_from_id(value: str) -> str:
    return value.split("__", 1)[1]


def _add_example(examples: list[str] | None, text: str) -> None:
    if examples is None:
        return
    if len(text) < 8 or text in examples:
        return
    # Keep examples compact and diverse.
    if len(examples) < 40:
        examples.append(text[:500])


def _label_aliases(label: str) -> list[str]:
    normalized = label.replace("/", " ").replace("-", " ")
    aliases = {_normalize_text(normalized).lower()}
    aliases.add(_slug(label).replace("_", " "))
    return sorted(alias for alias in aliases if alias)


def _terms(text: str) -> list[str]:
    words = [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", text.lower())
        if word not in STOPWORDS and len(word) <= 28
    ]
    terms: list[str] = []
    terms.extend(words)
    terms.extend(" ".join(pair) for pair in zip(words, words[1:], strict=False))
    return terms


def _slug(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
