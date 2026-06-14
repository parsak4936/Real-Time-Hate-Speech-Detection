# Evaluation Checkpoints

Safe snapshots of evaluation results at each stage. Use these to:
- Preserve Stage 3 results before starting Stage 4
- Load a prior state if supervisor requests new variants
- Track evaluation history without losing work

## Structure

Each checkpoint is a JSON file with:
- `timestamp`: When the checkpoint was created
- `name`: Descriptive name (e.g., `stage3_complete`, `stage4_multiagent_v1`)
- `notes`: What this checkpoint represents
- `benchmark_csv`: Which dataset was used
- `results_registry`: Full RESULTS_REGISTRY dict with all metrics

## Workflow

**Save a checkpoint:**
```python
save_checkpoint(
    "stage3_complete",
    notes="Tier-1 (73.8%), Tier-2 baseline (88.6%), memory (-9.73pp), RAG (-0.34pp)"
)
```

**List all checkpoints:**
```python
list_checkpoints()
```

**Load a checkpoint:**
```python
loaded_registry, metadata = load_checkpoint("stage3_complete_2026-06-14_181311.json")
RESULTS_REGISTRY = loaded_registry  # Restore into the notebook
```

## Example: Supervisor Asks for Low-Confidence Variant

1. **You just finished Stage 3.** Save it:
   ```python
   save_checkpoint("stage3_complete", notes="...")
   ```

2. **Supervisor asks:** "Can you re-evaluate on only the records where the agent was <80% confident?"

3. **You load low-confidence data and evaluate:**
   ```python
   # Load checkpoint to preserve Stage 3
   loaded_registry, _ = load_checkpoint("stage3_complete_2026-06-14_181311.json")
   
   # Now safely experiment with new data
   df_lowconf = load_benchmark("thesis_benchmark_lowconf_only.csv")
   # ... evaluate ... save results ...
   
   save_checkpoint("stage3_lowconf_variant", notes="52 low-conf records only")
   ```

4. **Original Stage 3 is still there**, no data loss.

## Naming Convention

- **By stage:** `stage3_complete`, `stage4_multiagent_v1`, `stage4_multiagent_v2`
- **By variant:** `stage3_lowconf_subset`, `stage4_rag_combined`
- **By timestamp:** Automatic suffix added by system (e.g., `2026-06-14_181311`)

## Recovery

If you accidentally overwrite `RESULTS_REGISTRY` or add incorrect data:
1. Run `list_checkpoints()` to find a safe prior state
2. Run `loaded_registry, _ = load_checkpoint("checkpoint_name.json")`
3. Restore: `RESULTS_REGISTRY = loaded_registry`
