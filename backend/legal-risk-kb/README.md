# ClauseGuide Legal Risk KB

This directory contains ClauseGuide's local hybrid legal-risk knowledge base.

## CUAD integration

The `source-data/cuad_v1` folder contains the actual CUAD v1 SQuAD-style JSON downloaded from `theatticusproject/cuad` on Hugging Face, with attribution metadata in `source-data/cuad_v1/attribution.json`.

CUAD facts used by ClauseGuide:

- Source: The Atticus Project CUAD v1
- Hugging Face dataset: `theatticusproject/cuad`
- License: CC BY 4.0
- Source file: `CUAD_v1/CUAD_v1.json`
- Contracts indexed locally: 510
- CUAD clause labels: 41
- Positive annotated answer spans derived locally: 13,823

Runtime does not load the full 40 MB source JSON. Run `python scripts/import_cuad.py` to regenerate compact artifacts:

- `source-data/cuad_v1/derived/cuad_clause_index.json`
- `source-data/cuad_v1/derived/cuad_contract_titles.json`
- `clause-taxonomy/cuad_clause_types.json`
- `clause-taxonomy/cuad_derived_aliases.json`

The app uses these compact artifacts for clause aliases, CUAD-backed examples, extraction reference text, analysis transparency, reports, and tests.

## Risk playbooks

Document-type playbooks define expected clauses, missing-clause severity, review focus, and false-positive guardrails. Risk-rule JSON files define evidence-supported triggers and mitigating terms. This avoids asking the LLM to freely infer legal risk from raw statutes or case law.
