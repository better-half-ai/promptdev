import tomllib
import torch
import torch.nn.functional as F
from pathlib import Path
from transformers import AutoTokenizer, AutoModelForSequenceClassification


class SentimentModel:
    """
    3-class sentiment classifier (negative / neutral / positive)
    using cardiffnlp/twitter-roberta-base-sentiment-latest.
    """

    def __init__(self, config_path: str = "config.toml"):
        cfg_file = Path(config_path)
        if not cfg_file.exists():
            raise FileNotFoundError(f"Configuration file not found: {cfg_file}")

        with open(cfg_file, "rb") as f:
            cfg = tomllib.load(f)

        model_cfg = cfg.get("model", {})
        infer_cfg = cfg.get("inference", {})

        self.model_dir = Path(model_cfg.get("dir", "models/cardiffnlp-roberta-sentiment"))
        self.device = torch.device(model_cfg.get("device", "cpu"))
        self.max_length = infer_cfg.get("max_length", 128)
        self.batch_size = infer_cfg.get("batch_size", 8)

        if not self.model_dir.exists():
            raise FileNotFoundError(
                f"Model directory missing: {self.model_dir}. Run setup.sh first."
            )

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_dir)
        self.model.to(self.device)
        self.model.eval()
        self.labels = list(self.model.config.id2label.values())

    def predict(self, texts):
        """Return [{'label': str, 'score': float}, ...] for given text(s)."""
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            return []

        results = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            inputs = self.tokenizer(
                batch,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=self.max_length,
            ).to(self.device)

            with torch.no_grad():
                logits = self.model(**inputs).logits
                probs = F.softmax(logits, dim=-1).cpu()

            for row in probs:
                score, idx = torch.max(row, dim=0)
                results.append(
                    {"label": self.labels[idx.item()], "score": float(score)}
                )
        return results
