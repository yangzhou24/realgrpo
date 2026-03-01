import argparse
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import torch
import torch.distributed as dist
from tqdm import tqdm
from transformers import AutoModelForCausalLM, AutoTokenizer


SYSTEM_INSTRUCTION = """
You are an expert AI Art Director. Your goal is to generate strictly aligned `pos_style` and `neg_style` keywords for image generation.

**HARD RULES (Violation = Failure):**
1. **Quantity:** Output EXACTLY 3 keywords for `pos_style` and 3 for `neg_style`.
2. **Strict Opposition:** `pos_style` and `neg_style` must be opposites on the same visual axis (e.g., "Sharp" vs "Blurry", "2D" vs "3D").
3. **NO Content Words:** Do NOT use content descriptions (e.g., "Cyborg", "Girl", "Shoujo", "Cat") as styles. Only use VISUAL descriptors (Lighting, Texture, Dimension).
4. **Banned Words:** NEVER use "Oil", "Oily", "Greasy" in `pos_style`, even for oil paintings (Use "Textured", "Impasto" instead).

**DECISION LOGIC:**

**STEP 1: Detect Visual Style**
Does the user explicitly specify an *artistic medium* or *rendering style*?
- **Styles:** Anime, Sketch, Pixel Art, Watercolor, 3D Render, Flat Design.
- **NOT Styles (Treat as Realism):** Cyborg, Monster, Japanese, Cute, Scary, Cyberpunk (unless "art" is added).

**STEP 2: Select Branch**

**BRANCH A: Implicit Realism (Default)**
*Trigger:* No explicit art style found (even if the subject is fantasy like "A dragon").
*Strategy:* Enhance realism, reject artificiality.
- **pos_style**: "Natural-lighting, Detailed, Real"
- **neg_style**: "Anime, Flat, Painting" (or "CG, 3D, Artificial")

**BRANCH B: Explicit Style**
*Trigger:* User asks for "Anime", "Sketch", "Icon", etc.
*Strategy:* Enhance that specific look, reject the opposite medium.
- *Example (Anime):* Pos="Flat, 2D, Cell-shaded" vs Neg="Photorealistic, 3D, Volumetric"
- *Example (Oil Painting):* Pos="Textured, Impasto, Brushstrokes" vs Neg="Smooth, Digital, Flat" (Note: "Oil" is avoided in Pos)

**EXAMPLES (Few-Shot):**

Input: "A black and white shoujo manga page."
Output: {"pos_style": "Monochrome, Lineart, Ink", "neg_style": "Color, 3D, Photorealistic"}
(Reasoning: "Shoujo" is genre, "Manga" implies Monochrome/Lineart style.)

Input: "A muscular pug dog in a textured oil painting."
Output: {"pos_style": "Heavy impasto, Textured, Brushstrokes", "neg_style": "Smooth, Digital, Photograph"}
(Reasoning: "Oil" is banned in pos_style to prevent artifacts, replaced with texture terms.)

Input: "A red Pikachu cyborg."
Output: {"pos_style": "Natural-lighting, Real, 8k", "neg_style": "Painting, Anime, Flat"}
(Reasoning: "Cyborg" is content. No style specified -> Default to Realism.)

**OUTPUT JSON:**
Return ONLY a JSON object:
{"pos_style": "word1, word2, word3", "neg_style": "word1, word2, word3"}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate style cfg with Qwen3 and directly export videos2caption_cfg.json."
    )
    parser.add_argument("--model-name", type=str, default="checkpoints/Qwen3-4B")
    parser.add_argument(
        "--input-json",
        type=str,
        default="data/flux_output/rl_embeddings/videos2caption.json",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/flux_output/rl_embeddings",
        help="Directory to save final videos2caption_cfg.json.",
    )
    parser.add_argument(
        "--output-json-name",
        type=str,
        default="videos2caption_cfg.json",
    )
    parser.add_argument(
        "--save-style-csv",
        action="store_true",
        help="If set, also save intermediate style csv.",
    )
    parser.add_argument(
        "--style-csv-name",
        type=str,
        default="video2caption_cfg.csv",
    )
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    return parser.parse_args()


def setup_distributed() -> Tuple[int, int, int, bool]:
    if "RANK" in os.environ and "WORLD_SIZE" in os.environ:
        dist.init_process_group(backend="nccl")
        rank = int(os.environ["RANK"])
        world_size = int(os.environ["WORLD_SIZE"])
        local_rank = int(os.environ["LOCAL_RANK"])
        torch.cuda.set_device(local_rank)
        print(f"[Init] Rank {rank}/{world_size} (Local {local_rank}) initialized.")
        return rank, world_size, local_rank, True

    print("Not running in distributed mode. Using single process.")
    return 0, 1, 0, False


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
    except Exception:
        return None
    return None


def load_model_and_tokenizer(
    model_name: str, local_rank: int, is_distributed: bool
) -> Tuple[AutoTokenizer, AutoModelForCausalLM]:
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if is_distributed:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map={"": local_rank},
        )
    else:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map="auto",
        )
    return tokenizer, model


def generate_style_cfg(
    caption: str,
    model: AutoModelForCausalLM,
    tokenizer: AutoTokenizer,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
) -> str:
    user_content = f"Caption: {caption}\nGenerate JSON response:"
    messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_content},
    ]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
    with torch.no_grad():
        generated_ids = model.generate(
            **model_inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
        )

    output_ids = generated_ids[0][len(model_inputs.input_ids[0]) :].tolist()
    try:
        index = len(output_ids) - output_ids[::-1].index(151668)
    except ValueError:
        index = 0
    return tokenizer.decode(output_ids[index:], skip_special_tokens=True).strip()


def build_caption_with_styles(caption: str, pos_style: str, neg_style: str) -> str:
    return f"{caption}|||{pos_style}|||{neg_style}"


def main() -> None:
    args = parse_args()
    rank, world_size, local_rank, is_distributed = setup_distributed()

    if rank == 0:
        print(f"Loading model from {args.model_name} ...")
    tokenizer, model = load_model_and_tokenizer(args.model_name, local_rank, is_distributed)
    if rank == 0:
        print("Model loaded.")
        print(f"Reading input json: {args.input_json}")

    try:
        with open(args.input_json, "r", encoding="utf-8") as f:
            all_data = json.load(f)
    except FileNotFoundError:
        if rank == 0:
            print(f"Input file not found: {args.input_json}")
        if is_distributed:
            dist.destroy_process_group()
        return

    indexed_data = list(enumerate(all_data))
    my_data = indexed_data[rank::world_size]
    print(f"[Rank {rank}] Processing {len(my_data)} / {len(all_data)} items.")

    local_results: List[Dict[str, Any]] = []
    iterator = tqdm(my_data, desc=f"GPU {rank}", position=rank) if world_size < 8 else my_data

    for original_idx, item in iterator:
        caption = item.get("caption", "")
        pos_style = ""
        neg_style = ""

        if caption:
            try:
                raw_content = generate_style_cfg(
                    caption=caption,
                    model=model,
                    tokenizer=tokenizer,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                )
                json_res = extract_json_from_text(raw_content)
                if json_res is not None:
                    pos_style = json_res.get("pos_style", "")
                    neg_style = json_res.get("neg_style", "")
            except Exception as e:
                print(f"[Rank {rank} Error] idx={original_idx} {e}")

        merged_item = dict(item)
        merged_item["caption"] = build_caption_with_styles(caption, pos_style, neg_style)

        local_results.append(
            {
                "index": original_idx,
                "merged_item": merged_item,
                "style_item": {
                    "prompt_embed_path": item.get("prompt_embed_path", ""),
                    "text_ids": item.get("text_ids", ""),
                    "pooled_prompt_embeds_path": item.get("pooled_prompt_embeds_path", ""),
                    "caption": caption,
                    "pos_style": pos_style,
                    "neg_style": neg_style,
                },
            }
        )

    if is_distributed:
        dist.barrier()
        gathered_data: List[Optional[List[Dict[str, Any]]]] = [None for _ in range(world_size)]
        dist.all_gather_object(gathered_data, local_results)
        all_results: List[Dict[str, Any]] = []
        for chunk in gathered_data:
            if chunk:
                all_results.extend(chunk)
    else:
        all_results = local_results

    if rank == 0:
        all_results.sort(key=lambda x: x["index"])
        merged_json = [x["merged_item"] for x in all_results]
        style_rows = [x["style_item"] for x in all_results]

        os.makedirs(args.output_dir, exist_ok=True)
        output_json_path = os.path.join(args.output_dir, args.output_json_name)
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(merged_json, f, indent=4, ensure_ascii=False)
        print(f"Saved merged json to: {output_json_path}")

        if args.save_style_csv:
            output_csv_path = os.path.join(args.output_dir, args.style_csv_name)
            pd.DataFrame(style_rows).to_csv(
                output_csv_path, index=False, encoding="utf-8", quoting=1
            )
            print(f"Saved style csv to: {output_csv_path}")

        print(
            f"Done. Total items: {len(merged_json)}. "
            f"Output is equivalent to preprocess + merge_styles in one run."
        )

    if is_distributed:
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
