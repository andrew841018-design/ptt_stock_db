
import logging
import os
import sys
import warnings
from typing import Optional

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    get_linear_schedule_with_warmup,
)

sys.path.insert(0, os.path.dirname(__file__))
from config import SENTIMENT_SCORES_TABLE, ARTICLES_TABLE, ARTICLE_LABELS_TABLE

BERT_MODEL = "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
from pg_helper import get_pg

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


LABEL_MAP     = {"negative": 0, "neutral": 1, "positive": 2}
ID_TO_LABEL   = {id_: label for label, id_ in LABEL_MAP.items()}
MODEL_DIR     = os.path.join(os.path.dirname(__file__), "models", "sentiment_bert")
MIN_SAMPLES   = 50
MAX_LEN       = 256
BATCH_SIZE    = 16
EPOCHS        = 3
LR            = 2e-5


class SentimentDataset(Dataset):
    def __init__(self, texts: list[str], labels: Optional[list[int]], tokenizer):
        self.labels = labels
        self.encodings = tokenizer(
            texts,
            max_length=MAX_LEN,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )

    def __len__(self):
        return self.encodings["input_ids"].shape[0]

    def __getitem__(self, idx):
        item = {key: val[idx] for key, val in self.encodings.items()}
        if self.labels is not None:
            item["labels"] = torch.tensor(self.labels[idx], dtype=torch.long)
        return item



def should_finetune() -> bool:
    if os.path.isdir(MODEL_DIR):
        return False
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {ARTICLE_LABELS_TABLE}")
            count = cur.fetchone()[0]
    return count >= MIN_SAMPLES


def load_labeled_data() -> tuple[list[str], list[int]]:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.title || ' ' || COALESCE(a.content, '') AS text,
                       al.label
                FROM {ARTICLE_LABELS_TABLE} al
                JOIN {ARTICLES_TABLE} a ON a.article_id = al.article_id
                ORDER BY al.labeled_at
            """)
            rows = cur.fetchall()

    if not rows:
        return [], []

    texts  = [text[:1000] for text, _ in rows]
    labels = [LABEL_MAP[label] for _, label in rows]
    logging.info("[BERT] 載入 %d 筆標注資料", len(texts))
    return texts, labels


def _split(texts, labels, val_ratio=0.1, test_ratio=0.1, seed=42):
    from sklearn.model_selection import train_test_split

    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=test_ratio, stratify=labels, random_state=seed
    )
    val_frac = val_ratio / (1 - test_ratio)
    x_train, x_val, y_train, y_val = train_test_split(
        x_train, y_train, test_size=val_frac, stratify=y_train, random_state=seed
    )
    return (x_train, y_train), (x_val, y_val), (x_test, y_test)



def train() -> None:
    texts, labels = load_labeled_data()

    if len(texts) < MIN_SAMPLES:
        logging.warning(
            "[BERT] 標注資料不足（%d 筆，需要至少 %d 筆），跳過 fine-tuning。"
            "請先用 labeling_tool.py 標注至少 %d 筆。",
            len(texts), MIN_SAMPLES, MIN_SAMPLES,
        )
        return

    logging.info("[BERT] 開始 fine-tuning，模型：%s", BERT_MODEL)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logging.info("[BERT] 使用裝置：%s", device)

    tokenizer = AutoTokenizer.from_pretrained(BERT_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BERT_MODEL, num_labels=3, ignore_mismatched_sizes=True
    ).to(device)

    (x_tr, y_tr), (x_va, y_va), _ = _split(texts, labels)
    train_loader = DataLoader(SentimentDataset(x_tr, y_tr, tokenizer), batch_size=BATCH_SIZE, shuffle=True)
    val_loader   = DataLoader(SentimentDataset(x_va, y_va, tokenizer), batch_size=BATCH_SIZE)

    optimizer  = torch.optim.AdamW(model.parameters(), lr=LR)
    total_steps = len(train_loader) * EPOCHS
    scheduler  = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=total_steps // 10, num_training_steps=total_steps
    )

    best_val_acc = 0.0
    for epoch in range(1, EPOCHS + 1):
        model.train()
        total_loss = 0.0
        for batch in train_loader:
            batch = {key: tensor.to(device) for key, tensor in batch.items()}
            outputs = model(**batch)
            loss = outputs.loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            total_loss += loss.item()

        avg_loss = total_loss / len(train_loader)

        model.eval()
        correct = total = 0
        with torch.no_grad():
            for batch in val_loader:
                batch = {key: tensor.to(device) for key, tensor in batch.items()}
                preds = model(**batch).logits.argmax(dim=-1)
                correct += (preds == batch["labels"]).sum().item()
                total   += batch["labels"].size(0)

        val_acc = correct / total
        logging.info("[BERT] Epoch %d/%d  loss=%.4f  val_acc=%.4f", epoch, EPOCHS, avg_loss, val_acc)

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            os.makedirs(MODEL_DIR, exist_ok=True)
            model.save_pretrained(MODEL_DIR)
            tokenizer.save_pretrained(MODEL_DIR)
            logging.info("[BERT] 儲存最佳模型（val_acc=%.4f）→ %s", best_val_acc, MODEL_DIR)

    logging.info("[BERT] Fine-tuning 完成，最佳 val_acc=%.4f", best_val_acc)



def evaluate() -> None:
    import seaborn as sns
    import matplotlib.pyplot as plt
    from sklearn.metrics import (
        classification_report, confusion_matrix, f1_score
    )

    texts, labels = load_labeled_data()
    if len(texts) < MIN_SAMPLES:
        logging.warning("[BERT] 標注資料不足，無法評估")
        return

    if not os.path.isdir(MODEL_DIR):
        logging.error("[BERT] 找不到 fine-tuned 模型，請先執行 train()")
        return

    _, _, (x_te, y_te) = _split(texts, labels)
    device    = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model     = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR).to(device)
    model.eval()

    loader = DataLoader(SentimentDataset(x_te, None, tokenizer), batch_size=BATCH_SIZE)
    preds  = []
    with torch.no_grad():
        for batch in loader:
            batch  = {key: tensor.to(device) for key, tensor in batch.items()}
            logits = model(**batch).logits
            preds.extend(logits.argmax(dim=-1).cpu().tolist())

    labels_str = [ID_TO_LABEL[label_id] for label_id in y_te]
    preds_str  = [ID_TO_LABEL[pred_id] for pred_id in preds]
    target_names = ["negative", "neutral", "positive"]

    logging.info("[BERT] Classification Report:\n%s", classification_report(labels_str, preds_str, target_names=target_names))
    macro_f1 = f1_score(y_te, preds, average="macro")
    logging.info("[BERT] Macro F1-score: %.4f", macro_f1)

    cm = confusion_matrix(labels_str, preds_str, labels=target_names)
    fig, ax = plt.subplots(figsize=(6, 5))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues",
                xticklabels=target_names, yticklabels=target_names, ax=ax)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(f"Confusion Matrix (Macro F1={macro_f1:.3f})")
    out_path = os.path.join(os.path.dirname(__file__), "models", "confusion_matrix.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    logging.info("[BERT] Confusion Matrix 儲存 → %s", out_path)
    plt.close(fig)



def _load_model_and_tokenizer():
    model_path = MODEL_DIR if os.path.isdir(MODEL_DIR) else BERT_MODEL
    if model_path == BERT_MODEL:
        logging.info("[BERT] 使用預訓練模型（zero-shot）：%s", BERT_MODEL)
    else:
        logging.info("[BERT] 使用 fine-tuned 模型：%s", MODEL_DIR)
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model     = AutoModelForSequenceClassification.from_pretrained(model_path)
    model.eval()
    return model, tokenizer



def run_batch_inference(batch_size: int = 500) -> None:
    with get_pg() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(*) FROM {ARTICLES_TABLE} a
                LEFT JOIN {SENTIMENT_SCORES_TABLE} ss ON ss.article_id = a.article_id
                WHERE ss.article_id IS NULL
            """)
            total = cur.fetchone()[0]

    if total == 0:
        logging.info("[BERT] 所有文章已有情緒分數，跳過")
        return

    logging.info("[BERT] 待推論：%d 篇文章（每批 %d 篇即時寫入）", total, batch_size)

    model, tokenizer = _load_model_and_tokenizer()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    processed = 0
    while True:
        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT a.article_id,
                           a.title || ' ' || COALESCE(a.content, '') AS text
                    FROM {ARTICLES_TABLE} a
                    LEFT JOIN {SENTIMENT_SCORES_TABLE} ss ON ss.article_id = a.article_id
                    WHERE ss.article_id IS NULL
                    ORDER BY a.article_id
                    LIMIT %s
                """, (batch_size,))
                rows = cur.fetchall()

        if not rows:
            break

        ids   = [article_id for article_id, _ in rows]
        texts = [text[:1000] for _, text in rows]

        INFERENCE_CHUNK = 16
        scores: list[float] = []
        for chunk_start in range(0, len(texts), INFERENCE_CHUNK):
            chunk_texts = texts[chunk_start:chunk_start + INFERENCE_CHUNK]
            encodings = tokenizer(
                chunk_texts, max_length=MAX_LEN, truncation=True,
                padding=True, return_tensors="pt",
            )
            encodings = {key: tensor.to(device) for key, tensor in encodings.items()}
            with torch.no_grad():
                logits = model(**encodings).logits
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
            scores.extend(float(prob[2] - prob[0]) for prob in probs)
            del encodings, logits, probs

        with get_pg() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    f"""
                    INSERT INTO {SENTIMENT_SCORES_TABLE} (article_id, score)
                    VALUES (%s, %s)
                    ON CONFLICT (article_id) DO UPDATE SET score = EXCLUDED.score
                    """,
                    zip(ids, scores),
                )

        processed += len(rows)
        logging.info("[BERT] 推論進度：%d / %d", processed, total)


