import tomllib
import torch
import torch.nn.functional as F
from pathlib import Path
from app.model import SentimentModel


class RelationalAffectModel(SentimentModel):
    """
    Extends 3-class sentiment output into multi-dimensional
    relational affect vectors for RRL (hurt, trust, hope, etc.).
    Loads mapping from config.toml → [relational] section.
    """

    def __init__(self, config_path: str = "config.toml"):
        super().__init__(config_path)

        cfg_file = Path(config_path)
        if not cfg_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {cfg_file}")

        with open(cfg_file, "rb") as f:
            cfg = tomllib.load(f)

        relational_cfg = cfg.get("relational")
        if not relational_cfg or "mapping" not in relational_cfg:
            raise KeyError("[relational].mapping missing in config.toml")

        self.mapping = torch.tensor(
            relational_cfg["mapping"], dtype=torch.float32, device=self.device
        )
        self.labels = list(self.model.config.id2label.values())

    def predict_relational(self, texts):
        """
        Return relational affect vector(s) for text(s):
        e_t = [hurt, trust, hope, frustration, curiosity]
        """
        base = super().predict(texts)
        results = []

        for b in base:
            label = b["label"].lower()
            if "neg" in label:
                row = 0
            elif "neu" in label:
                row = 1
            else:
                row = 2

            vec = self.mapping[row] * b["score"]
            results.append(
                {
                    "affect_vector": vec.tolist(),
                    "base_label": label,
                    "confidence": b["score"],
                }
            )

        return results


if __name__ == "__main__":
    m = RelationalAffectModel()
    text = "I’m disappointed you ignored me"
    print(f"\nInput: {text}")
    print("Output:", m.predict_relational(text))
