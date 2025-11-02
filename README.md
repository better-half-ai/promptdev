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

```bash
python -m app.model_relational "I love this!"
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

```bash
python -m app.model_relational "I’m disappointed you ignored me"
```

Output:

```
Base label: negative
Confidence: 0.88
Affect vector: [0.79, 0.00, 0.00, 0.62, 0.00]
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

## Quick Start: Try the Model

You can test the model immediately after installation — no coding required.

**Option 1: Single text input**

Run this command from the project directory:

```
python -m app.model_relational "I’m excited about this project!"
```

The program loads the sentiment model, analyzes your text, and prints results like:

```
Base label: positive
Confidence: 0.94
Affect vector: [0.00, 0.85, 0.74, 0.00, 0.55]
```

You can replace the quoted text with any sentence you want.
The program exits automatically after displaying the result.

---

**Option 2: Run from a JSON file**

1. Create a file named `input.json` containing an array of texts, for example:

   ```json
   ["I’m happy with how it went.", "This could have gone better.", "Maybe next time."]
   ```

2. Run:

   ```
   python -m app.model_relational input.json
   ```

3. The model will process each entry and display or save results in JSON format:

   ```json
   [
     {"text": "I’m happy with how it went.", "label": "positive", "affect_vector": [0.00, 0.84, 0.70, 0.00, 0.50]},
     {"text": "This could have gone better.", "label": "neutral", "affect_vector": [0.12, 0.08, 0.08, 0.12, 0.04]},
     {"text": "Maybe next time.", "label": "neutral", "affect_vector": [0.15, 0.10, 0.10, 0.15, 0.05]}
   ]
   ```

This allows you to analyze multiple sentences at once and keep the results for later use.

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
