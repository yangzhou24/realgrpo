export WANDB_DISABLED=true
export WANDB_BASE_URL="https://api.wandb.ai"
export WANDB_MODE=online

EXP_NAME="flux_realgrpo"
SCRIPTS_FILE="fastvideo/train_realgrpo_flux.py"

OUTPUT_DIR="data/flux_output/${EXP_NAME}"

mkdir -p "${OUTPUT_DIR}"

echo "Copying script to ${OUTPUT_DIR}..."
cp $SCRIPTS_FILE "${OUTPUT_DIR}/"

cp "$0" "${OUTPUT_DIR}/$(basename "$0")"

LOG_FILE="logs/train_realgrpo_flux_${EXP_NAME}_$(date +%Y%m%d_%H%M%S).txt"

scripts/run.sh \
    $SCRIPTS_FILE \
    --seed 42 \
    --pretrained_model_name_or_path checkpoints/flux \
    --vae_model_path checkpoints/flux \
    --cache_dir data/.cache \
    --data_json_path data/rl_embeddings/videos2caption_cfg.json \
    --gradient_checkpointing \
    --train_batch_size 1 \
    --num_latent_t 1 \
    --sp_size 1 \
    --train_sp_batch_size 1 \
    --dataloader_num_workers 4 \
    --gradient_accumulation_steps 4 \
    --max_train_steps 100 \
    --learning_rate 1e-5 \
    --mixed_precision bf16 \
    --checkpointing_steps 20 \
    --allow_tf32 \
    --cfg 0.0 \
    --output_dir "${OUTPUT_DIR}" \
    --h 720 \
    --w 720 \
    --t 1 \
    --sampling_steps 16 \
    --eta 0.3 \
    --lr_warmup_steps 0 \
    --sampler_seed 1223627 \
    --max_grad_norm 1.0 \
    --weight_decay 0.0001 \
    --use_hpsv2 \
    --num_generations 12 \
    --shift 3 \
    --use_group \
    --ignore_last \
    --timestep_fraction 0.6 \
    --clip_range 1e-4 \
    --adv_clip_max 5.0 \
    --init_same_noise \
    --kl_beta 0.0 \
    2>&1 | tee -a "${LOG_FILE}"
    