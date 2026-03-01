MODEL_PATH="checkpoints/flux"
OUTPUT_DIR="data/rl_embeddings"

LAUNCHER="torchrun \
    --nproc_per_node ${GPUS_PER_NODE} \
    --nnodes ${SLURM_NNODES} \
    --node_rank ${SLURM_NODEID} \
    --rdzv_backend c10d \
    --rdzv_endpoint ${MASTER_ADDR}:${MASTER_PORT} \
    --rdzv_id ${SLURM_JOB_ID} \
"

CMD="fastvideo/data_preprocess/preprocess_flux_embedding.py \
    --model_path $MODEL_PATH \
    --output_dir $OUTPUT_DIR \
    --prompt_dir "./assets/prompts.txt"
"

echo "Running command: $LAUNCHER $CMD"

$LAUNCHER $CMD