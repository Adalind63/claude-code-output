# -*- coding: utf-8 -*-
"""
续跑脚本：从最新 checkpoint 恢复训练，直到早停触发
"""
import os
import sys
from datetime import datetime

import numpy as np
import torch
from torch.nn import CrossEntropyLoss
from transformers import (
    DistilBertTokenizer,
    DistilBertForSequenceClassification,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback,
    DataCollatorWithPadding,
)
from datasets import Dataset
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
import pandas as pd
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# ===== 配置（与原脚本一致）=====
TRAIN_PATH = r"D:\项目流程\train.csv"
VAL_PATH = r"D:\项目流程\val.csv"
TEST_PATH = r"D:\项目流程\test.csv"
OUTPUT_MODEL_DIR = r"D:\项目流程\bert_stance_model"
OUTPUT_TEST_REPORT = r"D:\项目流程\test_evaluation_report.txt"

ENCODING = "utf-8-sig"
RANDOM_SEED = 42
LABEL2ID = {"tough": 0, "cooperate": 1, "neutral": 2}
ID2LABEL = {0: "tough", 1: "cooperate", 2: "neutral"}
NUM_LABELS = 3
MAX_LENGTH = 128
LEARNING_RATE = 2e-5
BATCH_SIZE = 8                # MX450 2GB 显存限制
GRADIENT_ACCUMULATION = 2      # 等效 batch = 8×2 = 16
MAX_EPOCHS = 10
EARLY_STOPPING_PATIENCE = 2
WEIGHT_DECAY = 0.01
WARMUP_RATIO = 0.06
FP16 = torch.cuda.is_available()

# ===== 加载数据 =====
def load_csv_to_dataset(filepath):
    df = pd.read_csv(filepath, encoding=ENCODING)
    df = df[df["text"].notna() & (df["text"].astype(str).str.strip() != "")]
    df = df[df["stance"].notna()]
    df["label"] = df["stance"].map(LABEL2ID)
    df = df[df["label"].notna()].copy()
    df["label"] = df["label"].astype(int)
    return Dataset.from_pandas(df[["text", "label"]], preserve_index=False)

# ===== Tokenize 函数 =====
def tokenize_fn(batch):
    return tokenizer(batch["text"], truncation=True, max_length=MAX_LENGTH, padding=False)

# ===== 评估指标 =====
def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=1)
    acc = accuracy_score(labels, predictions)
    precision, recall, f1, support = precision_recall_fscore_support(
        labels, predictions, labels=[0, 1, 2], zero_division=0
    )
    macro_f1 = f1.mean()
    metrics = {"eval_accuracy": round(acc, 4), "eval_macro_f1": round(macro_f1, 4)}
    for i, lbl in enumerate([0, 1, 2]):
        metrics[f"eval_f1_{ID2LABEL[lbl]}"] = round(f1[i], 4)
    return metrics

# ===== WeightedTrainer =====
class WeightedTrainer(Trainer):
    def __init__(self, class_weights, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.get("labels")
        outputs = model(**{k: v for k, v in inputs.items() if k != "labels"})
        loss_fn = CrossEntropyLoss(weight=self.class_weights.to(outputs.logits.device))
        loss = loss_fn(outputs.logits, labels)
        return (loss, outputs) if return_outputs else loss

# ===== 主函数 =====
def main():
    print("加载数据...")
    train_raw = load_csv_to_dataset(TRAIN_PATH)
    val_raw = load_csv_to_dataset(VAL_PATH)

    # ===== 加载 tokenizer 和模型 =====
    model_path = OUTPUT_MODEL_DIR
    if not os.path.exists(os.path.join(model_path, "config.json")):
        model_path = r"D:\项目流程\bert_stance_model\checkpoints\checkpoint-22164"

    print(f"从 {model_path} 加载模型...")
    global tokenizer
    tokenizer = DistilBertTokenizer.from_pretrained(model_path)
    model = DistilBertForSequenceClassification.from_pretrained(
        model_path,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    # ===== Tokenize（Windows 下 num_proc=1 避免多进程问题）=====
    train_ds = train_raw.map(tokenize_fn, batched=True, batch_size=1000, remove_columns=["text"])
    train_ds = train_ds.rename_column("label", "labels")
    val_ds = val_raw.map(tokenize_fn, batched=True, batch_size=1000, remove_columns=["text"])
    val_ds = val_ds.rename_column("label", "labels")

    # ===== 类别权重 =====
    labels_arr = np.array([item["labels"] for item in train_ds])
    from sklearn.utils.class_weight import compute_class_weight
    weights = compute_class_weight("balanced", classes=np.array([0, 1, 2]), y=labels_arr)
    class_weights = torch.tensor(weights, dtype=torch.float32)
    print(f"类别权重: {weights}")

    # ===== 训练参数 =====
    num_gpus = torch.cuda.device_count()
    effective_batch = BATCH_SIZE * GRADIENT_ACCUMULATION * max(1, num_gpus)
    total_steps = (len(train_ds) // effective_batch) * MAX_EPOCHS
    warmup_steps = int(total_steps * WARMUP_RATIO)

    training_args = TrainingArguments(
        output_dir=os.path.join(OUTPUT_MODEL_DIR, "checkpoints"),
        num_train_epochs=MAX_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
        adam_epsilon=1e-8,
        max_grad_norm=1.0,
        warmup_steps=warmup_steps,
        lr_scheduler_type="linear",
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_macro_f1",
        greater_is_better=True,
        logging_dir=os.path.join(OUTPUT_MODEL_DIR, "logs"),
        logging_strategy="steps",
        logging_steps=200,
        report_to="none",
        gradient_accumulation_steps=GRADIENT_ACCUMULATION,
        fp16=FP16,
        dataloader_num_workers=2,
        dataloader_pin_memory=True,
        seed=RANDOM_SEED,
    )

    data_collator = DataCollatorWithPadding(tokenizer=tokenizer, padding="longest", max_length=MAX_LENGTH)

    trainer = WeightedTrainer(
        class_weights=class_weights,
        model=model,
        args=training_args,
        data_collator=data_collator,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=EARLY_STOPPING_PATIENCE)],
    )

    # ===== 从 checkpoint 续跑 =====
    print(f"\n{'='*55}")
    print(f"  从 checkpoint 续跑训练")
    print(f"  当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  设备：{'GPU' if torch.cuda.is_available() else 'CPU'}")
    print(f"  早停容忍：{EARLY_STOPPING_PATIENCE} 轮（macro F1）")
    print(f"{'='*55}\n")

    start = datetime.now()
    trainer.train(resume_from_checkpoint=True)
    elapsed = datetime.now() - start

    print(f"\n训练耗时：{elapsed}")
    print(f"最优 macro F1：{trainer.state.best_metric:.4f}")
    print(f"最优 checkpoint：{trainer.state.best_model_checkpoint}")

    # 保存最优模型
    os.makedirs(OUTPUT_MODEL_DIR, exist_ok=True)
    trainer.save_model(OUTPUT_MODEL_DIR)
    tokenizer.save_pretrained(OUTPUT_MODEL_DIR)
    print(f"模型已保存至：{OUTPUT_MODEL_DIR}")

    # ===== 测试集评估 =====
    print(f"\n{'='*55}")
    print(f"  测试集评估")
    print(f"{'='*55}")

    test_raw = load_csv_to_dataset(TEST_PATH)
    test_ds = test_raw.map(tokenize_fn, batched=True, batch_size=1000, remove_columns=["text"])
    test_ds = test_ds.rename_column("label", "labels")

    predictions_output = trainer.predict(test_ds)
    logits = predictions_output.predictions
    y_true = predictions_output.label_ids
    y_pred = np.argmax(logits, axis=1)

    acc = accuracy_score(y_true, y_pred)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=[0, 1, 2], zero_division=0
    )
    macro_f1 = f1.mean()

    from sklearn.metrics import confusion_matrix
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1, 2])

    print(f"\n整体准确率：{acc:.4f}")
    print(f"宏平均 F1： {macro_f1:.4f}")
    print(f"\n{'类别':<12s} {'精确率':>8s} {'召回率':>8s} {'F1值':>8s} {'支持数':>8s}")
    for i, lbl in enumerate(["tough", "cooperate", "neutral"]):
        print(f"  {lbl:<12s} {precision[i]:>8.4f} {recall[i]:>8.4f} {f1[i]:>8.4f} {support[i]:>8d}")

    print(f"\n混淆矩阵（行=真实，列=预测）：")
    header = f"  {'':>12s}" + "".join(f"{lbl:>10s}" for lbl in ["tough", "cooperate", "neutral"])
    print(header)
    for i, lbl_row in enumerate(["tough", "cooperate", "neutral"]):
        row = f"  {lbl_row:<12s}" + "".join(f"{cm[i][j]:>10d}" for j in range(3))
        print(row)

    # 写报告
    lines = [
        "=" * 55,
        "  BERT 三分类立场微调 —— 测试集评估报告（续跑后）",
        "=" * 55,
        f"  生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  测试集样本数：{len(test_ds):,}",
        "",
        f"  整体准确率 (Accuracy)：{acc:.4f}",
        f"  宏平均 F1 (Macro F1)： {macro_f1:.4f}",
        "",
        "-" * 55,
        f"  {'类别':<12s} {'精确率':>8s} {'召回率':>8s} {'F1值':>8s} {'支持数':>8s}",
        "-" * 55,
    ]
    for i, lbl in enumerate(["tough", "cooperate", "neutral"]):
        lines.append(f"  {lbl:<12s} {precision[i]:>8.4f} {recall[i]:>8.4f} {f1[i]:>8.4f} {support[i]:>8d}")
    lines.append("-" * 55)
    lines.append("")
    lines.append("  混淆矩阵（行=真实标签，列=模型预测）：")
    lines.append(header)
    for i, lbl_row in enumerate(["tough", "cooperate", "neutral"]):
        row = f"  {lbl_row:<12s}" + "".join(f"{cm[i][j]:>10d}" for j in range(3))
        lines.append(row)
    lines.append("")
    lines.append("=" * 55)

    with open(OUTPUT_TEST_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n测试报告已保存至：{OUTPUT_TEST_REPORT}")
    print(f"\n{'='*60}")
    print(f"  续跑完成！最优 F1 = {trainer.state.best_metric:.4f}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
