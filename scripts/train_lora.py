"""LoRA Fine-Tuning Script for Qwen2.5-1.5B-Instruct on VehicleGPT Planner Data.

Designed for execution on free Google Colab (T4 GPU) or Kaggle (T4/P100 GPU).

Pipeline:
1. Loads base model Qwen/Qwen2.5-1.5B-Instruct in 4-bit (QLoRA) or 16-bit.
2. Attaches LoRA adapter with rank=16, alpha=32 across all projection layers:
   ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"].
3. Trains with SFTTrainer / Hugging Face Trainer on data/lora_train.jsonl with
   the exact prompt format matching VehicleGPT runtime inference.
4. Evaluates on data/lora_val.jsonl.
5. Merges LoRA adapter into base weights and exports to models/qwen2.5-1.5b-lora-merged/.
6. Provides downstream GGUF conversion & Q4_K_M quantization CLI commands.

GGUF Conversion & Quantization Commands (run in terminal after training):
-----------------------------------------------------------------------
# 1. Clone llama.cpp repository:
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp
pip install -r requirements.txt

# 2. Convert merged HuggingFace model to float16 GGUF:
python convert_hf_to_gguf.py ../models/qwen2.5-1.5b-lora-merged/ \
    --outfile ../models/qwen2.5-1.5b-lora-f16.gguf \
    --outtype f16

# 3. Quantize float16 GGUF to Q4_K_M:
./llama-quantize ../models/qwen2.5-1.5b-lora-f16.gguf \
    ../models/qwen2.5-1.5b-lora-q4_k_m.gguf Q4_K_M

# 4. Copy to VehicleGPT models directory:
cp ../models/qwen2.5-1.5b-lora-q4_k_m.gguf ../models/qwen2.5-1.5b-instruct-q4_k_m.gguf
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

def train_lora(
    base_model_name: str = "Qwen/Qwen2.5-1.5B-Instruct",
    train_data_path: str = "data/lora_train.jsonl",
    val_data_path: str = "data/lora_val.jsonl",
    output_dir: str = "checkpoints/lora_adapter",
    merged_output_dir: str = "models/qwen2.5-1.5b-lora-merged",
    epochs: int = 3,
    batch_size: int = 4,
    grad_accum_steps: int = 4,
    learning_rate: float = 2e-4,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
):
    print("================================================================")
    print(" VehicleGPT LoRA Fine-Tuning Pipeline (Colab / Kaggle)")
    print(f" Base Model:   {base_model_name}")
    print(f" Train Data:   {train_data_path}")
    print(f" LoRA Rank:    r={lora_r}, alpha={lora_alpha}")
    print(f" Output Dir:   {output_dir}")
    print("================================================================\n")

    try:
        import torch
        from datasets import load_dataset
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            TrainingArguments,
            BitsAndBytesConfig,
        )
        from peft import LoraConfig, get_peft_model, PeftModel
        from trl import SFTTrainer
    except ImportError as e:
        print("ERROR: Missing dependencies for GPU training. Install them using:")
        print("pip install torch transformers datasets peft trl bitsandbytes accelerate")
        print(f"Details: {e}")
        return

    # Check CUDA availability
    device_map = "auto" if torch.cuda.is_available() else "cpu"
    print(f"CUDA Available: {torch.cuda.is_available()} (Device: {device_map})")

    # Quantization config (QLoRA)
    bnb_config = None
    if torch.cuda.is_available():
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            bnb_4bit_use_double_quant=True,
        )

    # 1. Load Tokenizer & Base Model
    print("Loading base tokenizer and model...")
    tokenizer = AutoTokenizer.from_pretrained(base_model_name, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=bnb_config,
        device_map=device_map,
        trust_remote_code=True,
    )

    # 2. Configure LoRA
    print("Configuring LoRA adapters...")
    target_modules = [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj"
    ]
    peft_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        target_modules=target_modules,
        bias="none",
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # 3. Load Datasets
    print("Loading train and validation datasets...")
    dataset = load_dataset("json", data_files={"train": train_data_path, "validation": val_data_path})

    # 4. Training Arguments
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum_steps,
        learning_rate=learning_rate,
        weight_decay=0.01,
        warmup_ratio=0.03,
        logging_steps=10,
        evaluation_strategy="steps",
        eval_steps=50,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=2,
        fp16=torch.cuda.is_available() and not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
        report_to="none",
    )

    # 5. Trainer
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        dataset_text_field="prompt",
        max_seq_length=512,
        tokenizer=tokenizer,
    )

    # 6. Train
    print("\nStarting training loop...")
    trainer.train()

    # 7. Save adapter
    print(f"Saving fine-tuned adapter to {output_dir}...")
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)

    # 8. Merge and Unload
    if torch.cuda.is_available():
        print("Merging LoRA weights with base model...")
        base_model_reload = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            torch_dtype=torch.float16,
            device_map="cpu",
            trust_remote_code=True,
        )
        merged_model = PeftModel.from_pretrained(base_model_reload, output_dir)
        merged_model = merged_model.merge_and_unload()

        Path(merged_output_dir).mkdir(parents=True, exist_ok=True)
        print(f"Saving merged standalone model to {merged_output_dir}...")
        merged_model.save_pretrained(merged_output_dir)
        tokenizer.save_pretrained(merged_output_dir)
        print("Model export complete! Ready for GGUF conversion.")


def main():
    parser = argparse.ArgumentParser(description="VehicleGPT LoRA Training Script")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--train-data", default="data/lora_train.jsonl")
    parser.add_argument("--val-data", default="data/lora_val.jsonl")
    parser.add_argument("--output-dir", default="checkpoints/lora_adapter")
    parser.add_argument("--merged-dir", default="models/qwen2.5-1.5b-lora-merged")
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()

    train_lora(
        base_model_name=args.base_model,
        train_data_path=args.train_data,
        val_data_path=args.val_data,
        output_dir=args.output_dir,
        merged_output_dir=args.merged_dir,
        epochs=args.epochs,
    )


if __name__ == "__main__":
    main()
