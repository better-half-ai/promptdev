import torch
import pytest
from pprint import pprint
from app.model_relational import RelationalAffectModel


@pytest.fixture(scope="module")
def model():
    """Load relational affect model once per session."""
    m = RelationalAffectModel()
    print(f"\n[INIT] Loaded RelationalAffectModel with mapping:\n{m.mapping}")
    return m


def test_predict_relational_shape(model):
    """Print full relational output and verify shape."""
    text = "I’m disappointed you ignored me"
    out = model.predict_relational(text)
    print(f"\n[INPUT] {text}\n[OUTPUT]")
    pprint(out)
    vec = torch.tensor(out[0]["affect_vector"])
    vec_str = ", ".join(f"{v:.2f}" for v in vec.tolist())
    print(f"[VECTOR] [{vec_str}] | shape={vec.shape}, min={vec.min():.2f}, max={vec.max():.2f}")
    assert vec.ndim == 1 and vec.shape[0] == 5
    assert 0.0 <= vec.min() <= 1.0
    assert 0.0 <= vec.max() <= 1.0


def test_predict_relational_label_consistency(model):
    """Show each label and associated affect vector."""
    texts = [
        "I love talking to you",
        "I don't care anymore",
        "Maybe later",
    ]
    outs = model.predict_relational(texts)
    for t, o in zip(texts, outs):
        vec_str = ", ".join(f"{v:.2f}" for v in o["affect_vector"])
        print(f"\n[TEXT] {t}\n[BASE LABEL] {o['base_label']}\n[VECTOR] [{vec_str}]")
        assert o["base_label"] in ["positive", "negative", "neutral"]
        assert len(o["affect_vector"]) == 5


def test_projection_weighting(model):
    """Display projection math for verification with rounded string output."""
    sample = {"label": "positive", "score": 0.5}
    row = 2
    vec = model.mapping[row] * sample["score"]
    vec_str = ", ".join(f"{v:.2f}" for v in vec.tolist())
    print(f"\n[PROJECTION TEST] label={sample['label']} score={sample['score']}")
    print(f"[EXPECTED] trust = 0.9 * 0.5 = 0.45")
    print(f"[COMPUTED] [{vec_str}]")
    assert torch.isclose(vec[1], torch.tensor(0.45), atol=1e-6)
