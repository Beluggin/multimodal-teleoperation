# Fine-tuning Llama for raw mode

**Built with Llama.** This folder builds [Llama-3.2-3B-MITT-Tank](https://huggingface.co/Beluggin/Llama-3.2-3B-MITT-Tank), a LoRA fine-tune of Llama 3.2 3B. `MODEL_CARD.md` is its Hugging Face card, and the results are in [eval/README.md](../eval/README.md).

You need a GPU with 8 GB of memory, about 25 GB of disk, and approved access to `meta-llama/Llama-3.2-3B-Instruct` on Hugging Face. The libraries are in a separate environment from the rest of the repo: `pip install torch transformers peft accelerate bitsandbytes sentencepiece protobuf gguf`.

```
python3 train/make_dataset.py        # rebuilds train/data/ from word lists, fixed seed
python3 train/train_lora.py --base <weights> --out <adapter>
python3 train/merge_lora.py --base <weights> --adapter <adapter> --out <merged>
python3 <llama.cpp>/convert_hf_to_gguf.py <merged> --outtype bf16 --outfile Llama-3.2-3B-MITT-Tank.bf16.gguf
<llama.cpp>/build/bin/llama-quantize Llama-3.2-3B-MITT-Tank.bf16.gguf Llama-3.2-3B-MITT-Tank.Q4_K_M.gguf Q4_K_M
ollama create llama-3.2-3b-mitt-tank -f train/Modelfile   # with the GGUF next to the Modelfile
python3 eval/language_eval.py llama --model llama-3.2-3b-mitt-tank --prompt tuned --cases heldout.json
```

Download the weights file by file if `hf download --include` skips them, because that happened here with no error. Check that the two `.safetensors` files are there before training.

The training set leaves out every whole command in `eval/commands.json` and `eval/heldout.json`, and the build fails if one gets in. If you retrain because of a miss on `heldout.json`, write a new test list, since that one has then shaped the model.

Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.
