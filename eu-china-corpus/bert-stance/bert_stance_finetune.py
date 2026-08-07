# -*- coding: utf-8 -*-
"""
=============================================================================
BERT 三分类立场微调 —— 基于 Hugging Face Transformers + Trainer API
=============================================================================
功能概述：
  1. 加载 train/val/test CSV，标签 tough→0 / cooperate→1 / neutral→2
  2. 基座模型优先加载 DAPT 领域预训练权重，不存在则回退 bert-base-uncased
  3. Tokenize：最大长度 512，truncation + padding
  4. 训练：lr=2e-5，batch=16，epochs≤10，早停（macro F1 连续 2 轮不升）
  5. 损失函数：带类别权重的 CrossEntropyLoss（balanced，抑制中性样本过多）
  6. 评估：整体准确率、宏平均 F1、各类别 P/R/F1、混淆矩阵
  7. 输出模型 → D:\项目流程\bert_stance_model
  8. 测试报告 → D:\项目流程\test_evaluation_report.txt

依赖：pip install torch transformers datasets scikit-learn
=============================================================================
"""

import os
import math
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import torch
from torch.nn import CrossEntropyLoss
from transformers import (
    DistilBertTokenizer,
    DistilBertForSequenceClassification,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback,
    TrainerCallback,
    DataCollatorWithPadding,
)
from datasets import Dataset, DatasetDict
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix,
)
from sklearn.utils.class_weight import compute_class_weight

warnings.filterwarnings("ignore", category=UserWarning)

# =============================================================================
# 0. 全局配置（Windows 绝对路径）
# =============================================================================
TRAIN_PATH = r"D:\项目流程\train.csv"
VAL_PATH = r"D:\项目流程\val.csv"
TEST_PATH = r"D:\项目流程\test.csv"

DAPT_MODEL_PATH = r"D:\项目流程\bert_dapt_model"        # 领域预训练权重（优先）
FALLBACK_MODEL = "distilbert-base-uncased"                # 回退基座模型（6层，快60%）
OUTPUT_MODEL_DIR = r"D:\项目流程\bert_stance_model"      # 微调后模型保存路径
OUTPUT_TEST_REPORT = r"D:\项目流程\test_evaluation_report.txt"  # 测试报告

ENCODING = "utf-8-sig"
RANDOM_SEED = 42

# --- 标签映射 ---
LABEL2ID = {"tough": 0, "cooperate": 1, "neutral": 2}
ID2LABEL = {0: "tough", 1: "cooperate", 2: "neutral"}
NUM_LABELS = 3

# --- 训练参数 ---
MAX_LENGTH = 128   # 前128 token含核心立场信号，DistilBERT 6层加速
LEARNING_RATE = 2e-5
BATCH_SIZE = 16               # DistilBERT 更轻量，128 token 下 2GB 绰绰有余
MAX_EPOCHS = 10
EARLY_STOPPING_PATIENCE = 2     # macro F1 连续 2 轮不升则停
WEIGHT_DECAY = 0.01
WARMUP_RATIO = 0.06
FP16 = torch.cuda.is_available()


# =============================================================================
# 1. 选择基座模型
# =============================================================================

def select_base_model() -> str:
    """
    优先使用 DAPT 领域预训练模型，不存在则回退 bert-base-uncased。

    返回
    ----
    str
        模型路径或名称。
    """
    if os.path.isdir(DAPT_MODEL_PATH) and os.path.exists(
        os.path.join(DAPT_MODEL_PATH, "config.json")
    ):
        print(f"[模型] 加载领域预训练权重：{DAPT_MODEL_PATH}")
        return DAPT_MODEL_PATH
    else:
        print(f"[模型] DAPT 模型不存在，回退基座：{FALLBACK_MODEL}")
        return FALLBACK_MODEL


# =============================================================================
# 2. 数据加载与预处理
# =============================================================================

def load_csv_to_dataset(filepath: str) -> Dataset:
    """
    读取 CSV 并转为 Hugging Face Dataset。

    处理：过滤空 text/空 stance，标签数值化。

    参数
    ----
    filepath : str
        CSV 路径。

    返回
    ----
    Dataset
        含 text 和 label 列。
    """
    df = pd.read_csv(filepath, encoding=ENCODING)
    print(f"       {os.path.basename(filepath)}：{len(df):,} 条")

    # 过滤空值
    df = df[df["text"].notna() & (df["text"].astype(str).str.strip() != "")]
    df = df[df["stance"].notna()]

    # 标签数值化
    df["label"] = df["stance"].map(LABEL2ID)
    # 过滤未知标签
    df = df[df["label"].notna()].copy()
    df["label"] = df["label"].astype(int)

    return Dataset.from_pandas(df[["text", "label"]], preserve_index=False)


def tokenize_dataset(dataset: Dataset, tokenizer: DistilBertTokenizer) -> Dataset:
    """
    批量 tokenize：truncation + padding 到 max_length。

    参数
    ----
    dataset : Dataset
        原始数据集（含 text, label）。
    tokenizer : DistilBertTokenizer
        分词器。

    返回
    ----
    Dataset
        tokenized 数据集（含 input_ids, attention_mask, label）。
    """
    def tokenize_fn(batch: dict) -> dict:
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=MAX_LENGTH,
            padding=False,                 # 不填充，交由 DataCollator 动态填充
        )

    tokenized = dataset.map(
        tokenize_fn,
        batched=True,
        batch_size=1000,
        remove_columns=["text"],
        num_proc=2,
        desc="Tokenizing",
    )

    # 重命名并确保 label 列为整数
    tokenized = tokenized.rename_column("label", "labels")
    try:
        from datasets import Value
        tokenized = tokenized.cast_column("labels", Value("int64"))
    except ImportError:
        tokenized = tokenized.map(lambda x: {"labels": int(x["labels"])})

    return tokenized


# =============================================================================
# 3. 计算类别权重
# =============================================================================

def get_class_weights(train_dataset: Dataset) -> torch.Tensor:
    """
    从训练集计算 balanced 类别权重，用于 CrossEntropyLoss。

    公式：weight[c] = n_total / (n_classes * n_class_samples)
    cooperate 样本多 → 权重 < 1；tough / neutral 样本少 → 权重 > 1

    参数
    ----
    train_dataset : Dataset
        训练集（含 labels 列）。

    返回
    ----
    torch.Tensor
        [weight_tough, weight_cooperate, weight_neutral]
    """
    labels = []
    for item in train_dataset:
        labels.append(item["labels"])
    labels = np.array(labels)

    classes = np.array([0, 1, 2])
    weights = compute_class_weight("balanced", classes=classes, y=labels)
    weight_tensor = torch.tensor(weights, dtype=torch.float32)

    print(f"\n[权重] 各类别 CrossEntropy 权重：")
    for i, w in enumerate(weights):
        cnt = (labels == i).sum()
        print(f"       {ID2LABEL[i]:<12s} 样本 {cnt:>6,}  →  weight = {w:.4f}")

    return weight_tensor


# =============================================================================
# 4. 自定义 Trainer（支持加权损失 + 早停回调）
# =============================================================================

class WeightedTrainer(Trainer):
    """
    继承 Hugging Face Trainer，重写 compute_loss 以使用带类别权重的交叉熵。
    """

    def __init__(self, class_weights: torch.Tensor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        """
        使用加权 CrossEntropyLoss 计算损失。
        """
        labels = inputs.get("labels")
        outputs = model(**{k: v for k, v in inputs.items() if k != "labels"})
        logits = outputs.logits

        loss_fn = CrossEntropyLoss(weight=self.class_weights.to(logits.device))
        loss = loss_fn(logits, labels)

        return (loss, outputs) if return_outputs else loss


# =============================================================================
# 5. 评估指标
# =============================================================================

def compute_metrics(eval_pred) -> dict:
    """
    计算评估指标：整体准确率、宏平均 F1、各类别 P/R/F1。

    Trainer 每个 eval step 调用此函数获取指标字典。
    其中 "eval_macro_f1" 被 Trainer 用于早停和最优模型选择。

    参数
    ----
    eval_pred : EvalPrediction
        (logits, labels) 元组。

    返回
    ----
    dict
        指标名 → 值。
    """
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=1)

    # 整体准确率
    acc = accuracy_score(labels, predictions)

    # 各类别 P / R / F1（指定 labels 避免 missing class 的问题）
    precision, recall, f1, support = precision_recall_fscore_support(
        labels, predictions, labels=[0, 1, 2], zero_division=0
    )

    # 宏平均 F1
    macro_f1 = f1.mean()

    metrics = {
        "eval_accuracy": round(acc, 4),
        "eval_macro_f1": round(macro_f1, 4),
    }

    # 每类别 F1
    for i, lbl in enumerate([0, 1, 2]):
        metrics[f"eval_f1_{ID2LABEL[lbl]}"] = round(f1[i], 4)
        metrics[f"eval_precision_{ID2LABEL[lbl]}"] = round(precision[i], 4)
        metrics[f"eval_recall_{ID2LABEL[lbl]}"] = round(recall[i], 4)

    return metrics


# =============================================================================
# 6. 训练
# =============================================================================

def train_model(
    model: DistilBertForSequenceClassification,
    tokenizer: DistilBertTokenizer,
    train_dataset: Dataset,
    val_dataset: Dataset,
    class_weights: torch.Tensor,
    output_dir: str,
):
    """
    使用 Trainer API 执行三分类立场微调。

    参数
    ----
    model : DistilBertForSequenceClassification
        分类模型。
    tokenizer : DistilBertTokenizer
        分词器。
    train_dataset / val_dataset : Dataset
        训练 / 验证集。
    class_weights : torch.Tensor
        类别权重。
    output_dir : str
        模型保存目录。
    """
    print(f"\n{'='*55}")
    print(f"  开始立场分类微调训练")
    print(f"{'='*55}")

    # 计算总步数
    num_gpus = torch.cuda.device_count()
    effective_batch = BATCH_SIZE * max(1, num_gpus)
    total_steps = (len(train_dataset) // effective_batch) * MAX_EPOCHS
    warmup_steps = int(total_steps * WARMUP_RATIO)

    print(f"      GPU 数量：{num_gpus}")
    print(f"      训练样本：{len(train_dataset):,}")
    print(f"      验证样本：{len(val_dataset):,}")
    print(f"      学习率：{LEARNING_RATE}")
    print(f"      有效批次大小：{effective_batch}")
    print(f"      最大轮次：{MAX_EPOCHS}")
    print(f"      早停容忍：{EARLY_STOPPING_PATIENCE} 轮（macro F1）")
    print(f"      混合精度：{'FP16' if FP16 else '关闭'}")
    print()

    training_args = TrainingArguments(
        output_dir=os.path.join(output_dir, "checkpoints"),

        # --- 训练步数 ---
        num_train_epochs=MAX_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE,

        # --- 优化器 ---
        learning_rate=LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
        adam_epsilon=1e-8,
        max_grad_norm=1.0,

        # --- 调度器 ---
        warmup_steps=warmup_steps,
        lr_scheduler_type="linear",

        # --- 评估与早停（以 macro F1 为最优指标）---
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_macro_f1",
        greater_is_better=True,

        # --- 日志 ---
        logging_dir=os.path.join(output_dir, "logs"),
        logging_strategy="steps",
        logging_steps=200,
        report_to="none",

        # --- 性能 ---
        fp16=FP16,
        dataloader_num_workers=2,
        dataloader_pin_memory=True,
        seed=RANDOM_SEED,
    )

    data_collator = DataCollatorWithPadding(
        tokenizer=tokenizer,
        padding="longest",
        max_length=MAX_LENGTH,
    )

    trainer = WeightedTrainer(
        class_weights=class_weights,
        model=model,
        args=training_args,
        data_collator=data_collator,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
        callbacks=[
            EarlyStoppingCallback(
                early_stopping_patience=EARLY_STOPPING_PATIENCE,
            ),
        ],
    )

    # 训练
    start = datetime.now()
    trainer.train()
    elapsed = datetime.now() - start
    print(f"\n      训练耗时：{elapsed}")
    print(f"      最优 macro F1：{trainer.state.best_metric:.4f}")
    print(f"      最优轮次：{int(trainer.state.best_model_checkpoint.split('-')[-1]) if trainer.state.best_model_checkpoint else 'N/A'}")

    # 保存最优模型
    os.makedirs(output_dir, exist_ok=True)
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"\n      模型已保存至：{output_dir}")

    return trainer


# =============================================================================
# 7. 测试集评估 & 报告生成
# =============================================================================

def evaluate_and_report(
    trainer: Trainer,
    test_dataset: Dataset,
    label_names: list[str],
    output_path: str,
) -> None:
    """
    在测试集上评估模型，生成详细报告。

    包含：整体准确率、宏平均 F1、各类别 P/R/F1、混淆矩阵。

    参数
    ----
    trainer : Trainer
        已训练的 Trainer。
    test_dataset : Dataset
        测试集。
    label_names : list[str]
        标签名称列表 ["tough", "cooperate", "neutral"]。
    output_path : str
        报告输出路径。
    """
    print(f"\n{'='*55}")
    print(f"  测试集评估")
    print(f"{'='*55}")

    # 预测
    predictions_output = trainer.predict(test_dataset)
    logits = predictions_output.predictions
    y_true = predictions_output.label_ids
    y_pred = np.argmax(logits, axis=1)

    # 整体指标
    acc = accuracy_score(y_true, y_pred)

    # 各类别 P/R/F1
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=[0, 1, 2], zero_division=0
    )
    macro_f1 = f1.mean()

    # 混淆矩阵
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1, 2])

    # --- 打印到控制台 ---
    print(f"\n  整体准确率：{acc:.4f}")
    print(f"  宏平均 F1： {macro_f1:.4f}")
    print(f"\n  {'类别':<12s} {'精确率':>8s} {'召回率':>8s} {'F1值':>8s} {'支持数':>8s}")
    print(f"  {'-'*50}")
    for i, lbl in enumerate(label_names):
        print(f"  {lbl:<12s} {precision[i]:>8.4f} {recall[i]:>8.4f} "
              f"{f1[i]:>8.4f} {support[i]:>8d}")

    print(f"\n  混淆矩阵（行=真实，列=预测）：")
    header = f"  {'':>12s}" + "".join(f"{lbl:>10s}" for lbl in label_names)
    print(header)
    for i, lbl_row in enumerate(label_names):
        row = f"  {lbl_row:<12s}" + "".join(f"{cm[i][j]:>10d}" for j in range(len(label_names)))
        print(row)

    # --- 写入报告文件 ---
    lines = []
    lines.append("=" * 55)
    lines.append("  BERT 三分类立场微调 —— 测试集评估报告")
    lines.append("=" * 55)
    lines.append(f"  生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  测试集样本数：{len(test_dataset):,}")
    lines.append("")
    lines.append(f"  整体准确率 (Accuracy)：{acc:.4f}")
    lines.append(f"  宏平均 F1 (Macro F1)： {macro_f1:.4f}")
    lines.append("")
    lines.append("-" * 55)
    lines.append(f"  {'类别':<12s} {'精确率':>8s} {'召回率':>8s} {'F1值':>8s} {'支持数':>8s}")
    lines.append("-" * 55)
    for i, lbl in enumerate(label_names):
        lines.append(f"  {lbl:<12s} {precision[i]:>8.4f} {recall[i]:>8.4f} "
                     f"{f1[i]:>8.4f} {support[i]:>8d}")
    lines.append("-" * 55)
    lines.append("")
    lines.append("  混淆矩阵（行=真实标签，列=模型预测）：")
    header = f"  {'':>12s}" + "".join(f"{lbl:>10s}" for lbl in label_names)
    lines.append(header)
    for i, lbl_row in enumerate(label_names):
        row = f"  {lbl_row:<12s}" + "".join(f"{cm[i][j]:>10d}" for j in range(len(label_names)))
        lines.append(row)
    lines.append("")
    lines.append("=" * 55)

    report_text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n  测试报告已保存至：{output_path}")


# =============================================================================
# 8. 主流程
# =============================================================================

def main():
    print("=" * 60)
    print("  BERT 三分类立场微调")
    print(f"  启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    device = "GPU" if torch.cuda.is_available() else "CPU"
    print(f"  设备：{device}")
    if torch.cuda.is_available():
        print(f"  GPU 型号：{torch.cuda.get_device_name(0)}")
    print("=" * 60)

    # ---- [1] 选择基座模型 ----
    print("\n[1/7] 选择基座模型...")
    model_name_or_path = select_base_model()

    # ---- [2] 加载数据 ----
    print("\n[2/7] 加载数据...")
    train_raw = load_csv_to_dataset(TRAIN_PATH)
    val_raw = load_csv_to_dataset(VAL_PATH)
    test_raw = load_csv_to_dataset(TEST_PATH)

    # ---- [3] Tokenize ----
    print(f"\n[3/7] Tokenize（max_length={MAX_LENGTH}）...")
    tokenizer = DistilBertTokenizer.from_pretrained(model_name_or_path)
    train_ds = tokenize_dataset(train_raw, tokenizer)
    val_ds = tokenize_dataset(val_raw, tokenizer)
    test_ds = tokenize_dataset(test_raw, tokenizer)
    print(f"       训练集 tokenized：{len(train_ds):,} 条")
    print(f"       验证集 tokenized：{len(val_ds):,} 条")
    print(f"       测试集 tokenized：{len(test_ds):,} 条")

    # ---- [4] 计算类别权重 ----
    print("\n[4/7] 计算类别权重（balanced）...")
    class_weights = get_class_weights(train_ds)

    # ---- [5] 加载模型 ----
    print(f"\n[5/7] 加载分类模型（{NUM_LABELS} 标签）...")
    model = DistilBertForSequenceClassification.from_pretrained(
        model_name_or_path,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"       总参数：{total_params:,}  |  可训练：{trainable_params:,}")

    # ---- [6] 训练 ----
    print(f"\n[6/7] 训练（lr={LEARNING_RATE}, batch={BATCH_SIZE}, epochs≤{MAX_EPOCHS}）...")
    trainer = train_model(
        model, tokenizer, train_ds, val_ds, class_weights, OUTPUT_MODEL_DIR
    )

    # ---- [7] 测试集评估 & 报告 ----
    print(f"\n[7/7] 测试集评估 & 生成报告...")
    evaluate_and_report(trainer, test_ds, list(ID2LABEL.values()), OUTPUT_TEST_REPORT)

    print("\n" + "=" * 60)
    print("  🎉 微调完成！")
    print(f"  模型路径：{OUTPUT_MODEL_DIR}")
    print(f"  测试报告：{OUTPUT_TEST_REPORT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
