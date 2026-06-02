from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class PartyRole:
    name: str
    role: str
    side: str
    is_placeholder: bool


class PartyRoleExtractor:
    """Extracts parties and practical roles from real names or template placeholders."""

    role_keywords: tuple[tuple[str, tuple[str, ...], str], ...] = (
        (
            "borrower",
            ("borrower", "applicant", "student", "co-borrower", "guarantor"),
            "weaker_party",
        ),
        ("lender", ("bank", "lender", "financial institution"), "stronger_party"),
        ("tenant", ("tenant", "lessee", "licensee"), "tenant_side"),
        ("landlord", ("landlord", "lessor", "owner", "licensor"), "stronger_party"),
        ("employee", ("employee", "intern", "consultant"), "weaker_party"),
        ("employer", ("employer", "company"), "stronger_party"),
        ("client", ("client", "customer"), "client_side"),
        (
            "service_provider",
            ("service provider", "vendor", "contractor", "freelancer"),
            "provider_side",
        ),
        ("law_firm", ("law firm", "attorney", "advocate", "counsel"), "professional_side"),
        ("authority", ("authority", "government", "department", "corporation"), "stronger_party"),
    )

    between_re = re.compile(
        r"\b(?:by and )?between\s+(.{3,180}?)\s+and\s+(.{3,180}?)(?:\.|,|;|\(|\n|whereas\b)",
        re.IGNORECASE | re.DOTALL,
    )
    called_re = re.compile(
        r"(?P<name>[A-Z][A-Za-z0-9 .,&()/_-]{2,120})\s*(?:\([^)]*\))?\s*(?:hereinafter|hereafter)?\s*(?:called|referred to as|known as)\s+[\"']?(?P<role>[A-Za-z /_-]{3,40})",
        re.IGNORECASE,
    )
    placeholder_re = re.compile(r"_{3,}|\[.+?\]|<.+?>|name of|address of", re.IGNORECASE)

    def extract(self, full_text: str) -> list[PartyRole]:
        text = " ".join(full_text.split())
        parties: list[PartyRole] = []

        for match in self.between_re.finditer(text[:12000]):
            parties.extend(
                [
                    self._build_party(match.group(1)),
                    self._build_party(match.group(2)),
                ]
            )
            break

        for match in self.called_re.finditer(text[:16000]):
            name = self._clean(match.group("name"))
            role_text = self._clean(match.group("role")).lower()
            parties.append(self._build_party(name, role_hint=role_text))

        parties.extend(self._placeholder_parties(text[:8000]))
        return self._dedupe(parties)[:8]

    def _placeholder_parties(self, text: str) -> list[PartyRole]:
        lowered = text.lower()
        output: list[PartyRole] = []
        for role, keywords, side in self.role_keywords:
            for keyword in keywords:
                pattern = rf"{re.escape(keyword)}[^.:\n]{{0,80}}(?:____|\[|<|name of|address of)"
                if re.search(pattern, lowered, flags=re.IGNORECASE):
                    output.append(
                        PartyRole(
                            name=keyword.title(),
                            role=role,
                            side=side,
                            is_placeholder=True,
                        )
                    )
                    break
        return output

    def _build_party(self, value: str, role_hint: str | None = None) -> PartyRole:
        name = self._clean(value)
        role, side = self._infer_role(f"{role_hint or ''} {name}")
        return PartyRole(
            name=name,
            role=role,
            side=side,
            is_placeholder=bool(self.placeholder_re.search(value)),
        )

    def _infer_role(self, value: str) -> tuple[str, str]:
        lowered = value.lower()
        for role, keywords, side in self.role_keywords:
            if any(keyword in lowered for keyword in keywords):
                return role, side
        return "party", "unknown"

    @staticmethod
    def _clean(value: str) -> str:
        cleaned = re.sub(
            r"\s+(?:hereinafter|hereafter|called|referred to as)\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"^[,:;\s]+|[,:;\s]+$", "", cleaned)
        return " ".join(cleaned.split())[:140]

    @staticmethod
    def _dedupe(parties: list[PartyRole]) -> list[PartyRole]:
        output: list[PartyRole] = []
        seen: set[tuple[str, str]] = set()
        for party in parties:
            if not party.name or len(party.name) < 2:
                continue
            key = (party.name.lower(), party.role)
            if key in seen:
                continue
            seen.add(key)
            output.append(party)
        return output
