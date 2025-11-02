import inspect
import sys
import pytest
from app.model import SentimentModel

# Terminal colors (high contrast)
GREEN = "\033[92m"
MAGENTA = "\033[95m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


@pytest.fixture(scope="session")
def model():
    print(f"{BOLD}→ Initializing SentimentModel (3-class RoBERTa)...{RESET}")
    m = SentimentModel("config.toml")
    print(f"{BOLD}✓ Model loaded:{RESET} {m.model_dir}")
    print(f"  Labels: {m.labels}")
    return m


def log(label, score, text):
    color = {
        "positive": GREEN,
        "neutral": MAGENTA,
        "negative": RED,
    }.get(label.lower(), RESET)
    print(f"{color}[{label.upper():8}] {score:.4f} ← {text}{RESET}")


def debug_failure(func_name, text, pred, expected=None):
    print(f"\n{RED}{BOLD}✗ Test failure in:{RESET} {func_name}")
    print(f"  Input text: {text}")
    print(f"  Model output: {pred}")
    if expected is not None:
        print(f"  Expected label: {expected}")
    print(f"{BOLD}------------------------------------------------------------{RESET}\n")
    sys.stdout.flush()


# --- Functional Tests ---------------------------------------------------------

def test_single_string_inference(model):
    func_name = inspect.currentframe().f_code.co_name
    text = "I love this!"
    result = model.predict(text)
    try:
        assert isinstance(result, list)
        assert len(result) == 1
        assert "label" in result[0] and "score" in result[0]
    except AssertionError:
        debug_failure(func_name, text, result)
        raise
    log(result[0]["label"], result[0]["score"], text)


def test_batch_equivalence(model):
    func_name = inspect.currentframe().f_code.co_name
    texts = ["I love this!", "I hate this!"]
    try:
        single_results = [model.predict(t)[0]["label"] for t in texts]
        batch_results = [r["label"] for r in model.predict(texts)]
        assert single_results == batch_results
    except AssertionError:
        debug_failure(func_name, texts, {"single": single_results, "batch": batch_results})
        raise
    for t, l in zip(texts, single_results):
        print(f"{BOLD}✓ {t} → {l}{RESET}")


def test_reproducibility(model):
    func_name = inspect.currentframe().f_code.co_name
    text = "This product is amazing!"
    first = model.predict(text)[0]
    second = model.predict(text)[0]
    try:
        assert first == second
    except AssertionError:
        debug_failure(func_name, text, {"first": first, "second": second})
        raise
    log(first["label"], first["score"], text)


# --- Behavioral Tests ---------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("I absolutely love this product!", "positive"),    # 0.984
        ("This is the worst experience ever.", "negative"), # 0.945
        ("It's fine, not good but not terrible.", "neutral"), # 0.443
        ("I think it's okay, could be better though.", "positive"), # 0.720
        ("I can't stand how bad this is!", "negative"), # 0.950
        ("What a wonderful surprise!", "positive"), # 0.976
        ("It works, but I wouldn't recommend it.", "negative"), # 0.552
    ],
)
def test_behavioral_polarity(model, text, expected):
    """Verify classification across typical sentiment expressions."""
    func_name = inspect.currentframe().f_code.co_name
    pred = model.predict(text)[0]
    log(pred["label"], pred["score"], text)
    try:
        assert pred["label"].lower() == expected
    except AssertionError:
        debug_failure(func_name, text, pred, expected)
        raise


# --- Robustness Tests (English-only) ------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "LOVE this!!! 💯🔥",
        "terrible :(",
        "Meh.",
        "This... works?",
        "good GOOD good",
        "Bad BAD bad",
        "  extra   spaces   everywhere  ",
        "Mixed feelings about this one 🤔",
    ],
)
def test_robustness_nonstandard_inputs(model, text):
    func_name = inspect.currentframe().f_code.co_name
    pred = model.predict(text)[0]
    try:
        assert pred["label"].lower() in {"positive", "neutral", "negative"}
    except AssertionError:
        debug_failure(func_name, text, pred)
        raise
    log(pred["label"], pred["score"], text)


def test_long_input(model):
    func_name = inspect.currentframe().f_code.co_name
    long_text = " ".join(["I love this."] * 200)
    pred = model.predict(long_text)[0]
    try:
        assert pred["label"].lower() in {"positive", "neutral", "negative"}
    except AssertionError:
        debug_failure(func_name, long_text, pred)
        raise
    log(pred["label"], pred["score"], f"[long text] ({len(long_text.split())} words)")
