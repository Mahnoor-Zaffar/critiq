# Critiq — Evaluation Framework

> Document type: quality / evaluation specification
> Related: `PRD.md` (success metrics), `review-pipeline.md`

---

## 1. Overview

Critiq's defense against AI noise is a **quality gate**, and its calibration
must come from data, not intuition. The evaluation framework is non-negotiable:
it measures whether Critiq's findings are actually useful and precise.

The product should optimize primarily for **precision** (fewer bad comments)
over recall (catching everything).

---

## 2. Evaluation Dataset

Collect real PRs and manually label findings.

### Record shape

```
PR
 ├── repository
 ├── number
 ├── diff
 ├── context (files, graph)
 └── findings[]
      ├── id
      ├── category
      ├── file_path
      ├── line_start / line_end
      ├── severity
      ├── valid          # human verdict: is this a real issue?
      ├── severity_correct
      ├── useful         # human verdict: would you keep this comment?
      └── human_action   # e.g. accepted / dismissed / resolved / edited
```

---

## 3. Metrics

| Metric | Definition | Target |
| ------ | ---------- | ------ |
| **Precision** | valid findings / total findings | >85% |
| **Useful finding rate** | comments devs would keep / total | >70% |
| **False-positive rate** | invalid findings / total | <15% |
| **Recall / Coverage** | detected valid findings / all known valid findings | >60% initially |

---

## 4. Benchmarking

Compare Critiq against experienced human engineers per category.

| Category | Human | Critiq |
| -------- | ----- | ------ |
| Correctness | 82% | 78% |
| Security | 91% | 88% |
| Architecture | 76% | 73% |
| Performance | 69% | 64% |
| Testing | 84% | 81% |
| False positives | 8% | 12% |

Baseline targets above are illustrative; the real numbers come from running the
dataset.

---

## 5. Threshold Calibration

Use the dataset to tune:

- `confidence_threshold`
- `severity_threshold`
- evidence gate strictness
- dedup aggressiveness

Adjusting the confidence gate trades precision vs recall. The product
bullishness should default toward precision.

---

## 6. Test Harness (planned)

- `tests/evaluation/` holds fixtures: sample PRs, expected findings, human
  verdicts.
- A runner computes precision/recall/FP over a configurable split.
- A regression suite ensures a change does not degrade review quality.

---

## 7. Definition of "Good Review"

A high-quality Critiq review is one where an experienced Staff Engineer says:

> "Yes, that's exactly the issue I would have raised."

That is the north-star the evaluation framework exists to measure.
