import os
import re
import argparse
import torch
import torch.distributed as dist
from pathlib import Path
from diffusers import FluxPipeline, FluxTransformer2DModel
from torch.utils.data import Dataset, DistributedSampler

class PromptDataset(Dataset):
    def __init__(self, file_path, max_prompts=160):
        with open(file_path, 'r') as f:
            self.prompts = [line.strip() for line in f if line.strip()][:max_prompts]
        
    def __len__(self):
        return len(self.prompts)

    def __getitem__(self, idx):
        return self.prompts[idx]

def sanitize_filename(text, max_length=200):
    sanitized = re.sub(r'[\\/:*?"<>|]', '_', text)
    return sanitized[:max_length].rstrip() or "untitled"

def distributed_setup():
    rank = int(os.environ['RANK'])
    local_rank = int(os.environ['LOCAL_RANK'])
    world_size = int(os.environ['WORLD_SIZE'])
    
    dist.init_process_group(backend="nccl")
    torch.cuda.set_device(local_rank)
    return rank, local_rank, world_size

def parse_args():
    parser = argparse.ArgumentParser(description="Distributed FLUX inference script.")
    parser.add_argument("--base_model_path", type=str, default="./checkpoints/flux")
    parser.add_argument(
        "--finetuned_transformer_path",
        type=str,
        default="data/flux_output/flux_realgrpo/checkpoint-100-0",
    )
    parser.add_argument("--prompt_file", type=str, default="./assets/MJHQ-30K_prompts_shuffled.txt")
    parser.add_argument(
        "--output_dir",
        type=str,
        default="data/flux_output/flux_realgrpo/infer_results_MJHQ-30K/checkpoint-100-0",
    )
    parser.add_argument("--max_prompts", type=int, default=160)
    parser.add_argument("--guidance_scale", type=float, default=3.5)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--num_inference_steps", type=int, default=50)
    parser.add_argument("--max_sequence_length", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    args, _ = parser.parse_known_args()
    return args

def main():
    args = parse_args()
    rank, local_rank, world_size = distributed_setup()

    # --- 修改开始 ---
    
    # 1. 定义你的模型路径
    base_model_path = args.base_model_path
    
    # !! 你需要将这里改成你微调后的 transformer 权重的实际路径 !!
    finetuned_transformer_path = args.finetuned_transformer_path

    if rank == 0:
        print(f"Loading finetuned transformer from: {finetuned_transformer_path}")

    # 2. 单独加载你微调过的 transformer 组件
    # 注意：我们在这里不使用 .to("cuda")，让 pipeline 在最后一步统一处理
    transformer = FluxTransformer2DModel.from_pretrained(
        finetuned_transformer_path,
        torch_dtype=torch.bfloat16,
        use_safetensors=True
    )

    if rank == 0:
        print(f"Loading base pipeline from: {base_model_path}")

    # 3. 加载基础 pipeline，并注入微调过的 transformer
    pipe = FluxPipeline.from_pretrained(
        base_model_path,
        transformer=transformer,  # <-- 注入你的 transformer
        torch_dtype=torch.bfloat16,
        use_safetensors=True
    ).to("cuda")  # 这会将所有组件（包括你注入的）移动到正确的GPU

    # --- 修改结束 ---

    dataset = PromptDataset(args.prompt_file, max_prompts=args.max_prompts)
    sampler = DistributedSampler(
        dataset,
        num_replicas=world_size,
        rank=rank,
        shuffle=False
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 同步所有进程，确保目录都已创建
    dist.barrier() 

    for idx in sampler:
        prompt = dataset[idx]
        try:
            # 你的 generator 已正确设置
            generator = torch.Generator(device=f"cuda:{local_rank}")
            generator.manual_seed(args.seed + idx + rank*1000) 
            
            image = pipe(
                prompt,
                guidance_scale=args.guidance_scale,
                height=args.height,
                width=args.width,
                num_inference_steps=args.num_inference_steps,
                max_sequence_length=args.max_sequence_length,
                generator=generator
            ).images[0]

            filename = sanitize_filename(prompt)
            save_path = output_dir / f"{filename}.jpg"
            
            counter = 1
            while save_path.exists():
                save_path = output_dir / f"{filename}_{counter}.jpg"
                counter += 1

            image.save(save_path)
            print(f"[Rank {rank}] Generated: {save_path.name}")

        except Exception as e:
            print(f"[Rank {rank}] Error processing '{prompt[:20]}...': {str(e)}")

    dist.destroy_process_group()

if __name__ == "__main__":
    main()
