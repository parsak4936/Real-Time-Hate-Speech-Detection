# src/agents/distilbert_adapter.py
import torch
import numpy as np
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification
from .base_adapters import ModelAdapter
import os

class DistilBertAdapter(ModelAdapter):
    def __init__(self, model_dir: str = "../../models/bert_final"):
        self.tokenizer = DistilBertTokenizer.from_pretrained(model_dir)
        self.model = DistilBertForSequenceClassification.from_pretrained(model_dir)
        self.model.eval()
        # optional: torch.set_grad_enabled(False)  # saves a few MB

    def predict(self, text: str) -> dict:
        inputs = self.tokenizer(text,
                                return_tensors="pt",
                                truncation=True,
                                padding=True,
                                max_length=128)
        with torch.no_grad():
            logits = self.model(**inputs).logits.squeeze()
        probs = torch.nn.functional.softmax(logits, dim=-1).cpu().numpy()
        pred_idx = int(np.argmax(probs))
        labels = {0: "HATE", 1: "OFFENSIVE", 2: "NORMAL"}
        return {
            "label": labels[pred_idx],
            "score": float(probs[pred_idx]),
            "raw_logits": logits.tolist()
        }

    def explain(self, text: str) -> str:
        # Delegates to the Captum‑based utility (see src/tools/explain_flag.py)
        from .explain_util import token_attribution_heatmap
        return token_attribution_heatmap(self.model, self.tokenizer, text)
