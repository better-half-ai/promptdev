# Sentiment & Relational Affect Analysis

This repository provides a standalone sentiment-analysis system.

It includes:

* A RoBERTa-based 3-class sentiment classifier
* A configurable relational-affect extension producing 5-D emotional vectors
* Full pytest coverage and human-readable diagnostics

---

## Architecture

```
text → SentimentModel (RoBERTa) → label/score
     → RelationalAffectModel (mapping) → affect_vector[5]
```

| Component                 | File                             | Description                                                                    |
| ------------------------- | -------------------------------- | ------------------------------------------------------------------------------ |
| **SentimentModel**        | `app/model.py`                   | Wraps `cardiffnlp/twitter-roberta-base-sentiment-latest` for 3-class sentiment |
| **RelationalAffectModel** | `app/model_relational.py`        | Extends sentiment output to `[hurt, trust, hope, frustration, curiosity]`      |
| **Tests**                 | `tests/test_model_relational.py` | Validates shape, label consistency, projection math                            |
| **Configuration**         | `config.toml`                    | Defines model paths, inference parameters, and relational mapping              |

---

## Installation

```bash
git clone https://github.com/better-half-ai/sentiment-analysis.git
cd sentiment-analysis
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

Requirements: `torch`, `transformers`, `pytest`, `tomli` (Python 3.11+).

---

## Models

### Base Sentiment Model

**File:** `app/model.py`

* Uses `cardiffnlp/twitter-roberta-base-sentiment-latest`
* Classes: negative, neutral, positive
* Returns confidence-weighted label(s)

```python
from app.model import SentimentModel

m = SentimentModel()
print(m.predict("I love this!"))
# → [{'label': 'positive', 'score': 0.98}]
```

---

### Relational Affect Model

**File:** `app/model_relational.py`

Extends the base model to five relational dimensions:

```
[hurt, trust, hope, frustration, curiosity]
```

It loads the mapping from `config.toml`, multiplies each sentiment confidence by its
configured relational weights, and returns a structured affect vector.

Example:

```python
from app.model_relational import RelationalAffectModel

m = RelationalAffectModel()
print(m.predict_relational("I’m disappointed you ignored me"))
# → {'affect_vector': [0.79, 0.00, 0.00, 0.62, 0.00],
#    'base_label': 'negative',
#    'confidence': 0.88}
```

---

## Configuration

**File:** `config.toml`

```toml
[model]
dir = "models/cardiffnlp-roberta-sentiment"
device = "cpu"

[inference]
max_length = 128
batch_size = 8

[relational]
# rows: negative, neutral, positive
# columns: hurt, trust, hope, frustration, curiosity
mapping = [
  [0.9, 0.0, 0.0, 0.7, 0.0],
  [0.3, 0.2, 0.2, 0.3, 0.1],
  [0.0, 0.9, 0.8, 0.0, 0.6],
]
```

You can tune or retrain this mapping.
Each row corresponds to a sentiment label; each column defines a relational-affect axis.

To learn the mapping empirically, train a small projection head:

```
L = MSE(W·p_sentiment, r_target)
```

Then replace the static numbers with the learned weights in this table.

---

## Testing

Run all tests:

```bash
pytest -v -s
```

Example output:

```
[INIT] Loaded RelationalAffectModel with mapping:
tensor([[0.9000, 0.0000, 0.0000, 0.7000, 0.0000],
        [0.3000, 0.2000, 0.2000, 0.3000, 0.1000],
        [0.0000, 0.9000, 0.8000, 0.0000, 0.6000]])

[TEXT] I love talking to you
[BASE LABEL] positive
[VECTOR] [0.00, 0.87, 0.78, 0.00, 0.58]
```

All tests should pass:

```
tests/test_model_relational.py::test_predict_relational_shape PASSED
tests/test_model_relational.py::test_predict_relational_label_consistency PASSED
tests/test_model_relational.py::test_projection_weighting PASSED
```

---

## Usage Summary

**Command-line**

```bash
python -m app.model_relational
```

**Programmatic**

```python
from app.model_relational import RelationalAffectModel
m = RelationalAffectModel()
print(m.predict_relational("It works fine, nothing special."))
```

---

## Project Structure

```
sentiment-analysis/
├── app/
│   ├── __init__.py
│   ├── model.py                 # 3-class sentiment model
│   └── model_relational.py      # relational affect extension
├── data/
│   ├── emotions.json
│   └── groups.json
├── tests/
│   ├── test_model_sentiment.py
│   └── test_model_relational.py
├── config.toml
├── README.md
└── pyproject.toml
```

---

## License

MIT License © 2025
Use freely with attribution.
