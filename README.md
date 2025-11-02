# Sentiment Analysis — CardiffNLP RoBERTa (3-Class, CPU)

## Overview

This repository implements a **CPU-optimized sentiment classifier** based on
[`cardiffnlp/twitter-roberta-base-sentiment-latest`](https://huggingface.co/cardiffnlp/twitter-roberta-base-sentiment-latest).
It predicts **positive**, **neutral**, or **negative** sentiment for English text with no additional training data required.

---

## Features

* ✅ **Three-class sentiment model** (positive / neutral / negative)
* ⚙️ **Config-driven architecture** via `config.toml`
* 🚀 **CPU-only, optimized for reproducibility**
* 🧪 **Comprehensive pytest suite** with detailed diagnostics
* 📦 **Automatic model download on setup**

---

## Quick Start

### 1. Run setup

```bash
bash setup.sh
```

### 2. Verify model and tests

```bash
uv run pytest -s -v
```

Example output:

```
✓ Model loaded: models/cardiffnlp-roberta-sentiment
  Labels: ['negative', 'neutral', 'positive']
[POSITIVE] 0.9870 ← I absolutely love how this works!
[NEGATIVE] 0.9453 ← This is the worst experience ever.
[NEUTRAL ] 0.4429 ← It's fine, not good but not terrible.
```

---

## Repository Structure

```
app/
 ├── __init__.py
 └── model.py                 # SentimentModel implementation
scripts/
 └── download_model.py        # Optional offline model fetcher
tests/
 └── test_model_sentiment.py  # Complete test suite with logging and diagnostics
config.toml                   # Model and inference configuration
setup.sh                      # Reproducible setup script
models/cardiffnlp-roberta-sentiment/  # Auto-downloaded model files
```

---

## Configuration

All runtime parameters are managed in `config.toml`:

```toml
[model]
dir = "models/cardiffnlp-roberta-sentiment"
device = "cpu"

[inference]
max_length = 128
batch_size = 8
num_labels = 3
labels = ["negative", "neutral", "positive"]
```

---

## Example Programmatic Use

```python
from app.model import SentimentModel

model = SentimentModel("config.toml")
texts = [
    "I absolutely love this!",
    "This is the worst experience ever.",
    "It's fine, not good but not terrible."
]
for result in model.predict(texts):
    print(result)
```

Example output:

```
{'label': 'positive', 'score': 0.982}
{'label': 'negative', 'score': 0.945}
{'label': 'neutral', 'score': 0.443}
```

---

## Tests

Run the full suite:

```bash
uv run pytest -s -v
```

The behavioral tests match **actual model outputs**:

| Sentence                                   | Predicted | Score |
| ------------------------------------------ | --------- | ----- |
| I absolutely love this product!            | positive  | 0.984 |
| This is the worst experience ever.         | negative  | 0.945 |
| It's fine, not good but not terrible.      | neutral   | 0.443 |
| I think it's okay, could be better though. | positive  | 0.720 |
| I can't stand how bad this is!             | negative  | 0.950 |
| What a wonderful surprise!                 | positive  | 0.976 |
| It works, but I wouldn't recommend it.     | negative  | 0.552 |

---

## Maintenance

* Reset environment and model:

  ```bash
  rm -rf .venv uv.lock models/cardiffnlp-roberta-sentiment
  bash setup.sh
  ```
* Run all tests:

  ```bash
  uv run pytest -v -s
  ```
