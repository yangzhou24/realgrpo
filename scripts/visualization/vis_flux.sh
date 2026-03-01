sbatch -p eb3d_t \
  --job-name=vis_flux \
  --gres=gpu:8 \
  --cpus-per-task=4 \
  --ntasks-per-node=1 \
  --nodes=2 \
  --output=logs/vis_flux_%j.log \
  scripts/run.sh scripts/visualization/vis_flux.py \
  --finetuned_transformer_path data/flux_output/flux_realgrpo/checkpoint-80-0 \
  --prompt_file ./assets/prompts.txt \
  --max_prompts 32 \
  --output_dir data/flux_output/flux_realgrpo/infer_results/checkpoint-80-0 \