import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.pipeline_utils import PipelineStateManager, generate_run_id

PROJECT_ROOT = Path(__file__).parent.parent

def main():
    print(">>> ADVERSARIAL TEST: FAIL-SAFE CLEANUP")
    
    # 1. Setup Mock State
    # Run 1: COMPLETE (Should be untouched)
    # Run 2: STAGE_1_START (Should be FAILED)
    # Run 3: FAILED (Should be untouched)
    
    d_path = PROJECT_ROOT / "backtest_directives" / "active" / "Workflow_Test_01.txt"
    if not d_path.exists():
        print("MISSING DIRECTIVE")
        return

    # Use fake symbols to avoid messing up real runs
    s1 = "MOCK_COMPLETE"
    s2 = "MOCK_HANGING"
    s3 = "MOCK_FAILED"
    
    # Init
    r1, _ = generate_run_id(d_path, s1)
    r2, _ = generate_run_id(d_path, s2)
    r3, _ = generate_run_id(d_path, s3)
    
    m1 = PipelineStateManager(r1)
    m1.initialize()
    m1.transition_to("PREFLIGHT_START")
    m1.transition_to("PREFLIGHT_COMPLETE")
    m1.transition_to("STAGE_1_START")
    m1.transition_to("STAGE_1_COMPLETE")
    m1.transition_to("STAGE_2_START")
    m1.transition_to("STAGE_2_COMPLETE")
    m1.transition_to("STAGE_3_START")
    m1.transition_to("STAGE_3_COMPLETE")
    m1.transition_to("STAGE_3A_START")
    m1.transition_to("STAGE_3A_COMPLETE")
    m1.transition_to("COMPLETE")
    
    m2 = PipelineStateManager(r2)
    m2.initialize()
    m2.transition_to("PREFLIGHT_START")
    m2.transition_to("PREFLIGHT_COMPLETE")
    m2.transition_to("STAGE_1_START") # HANGING HERE
    
    m3 = PipelineStateManager(r3)
    m3.initialize()
    m3.transition_to("FAILED")
    
    print(f"Setup Complete.")
    print(f"R1 ({s1}) -> COMPLETE")
    print(f"R2 ({s2}) -> STAGE_1_START (Target for Cleanup)")
    print(f"R3 ({s3}) -> FAILED")
    
    # 2. Trigger Cleanup Logic Loop (Simulated from run_pipeline.py)
    run_ids = [r1, r2, r3]
    
    print("\n>>> EXECUTING CLEANUP SIMULATION...")
    import json
    
    for rid in run_ids:
        try:
            mgr = PipelineStateManager(rid)
            if mgr.state_file.exists():
                 with open(mgr.state_file, 'r') as f:
                     data = json.load(f)
                 state = data['current_state']
                 print(f"Checking {rid}: {state}")
                 
                 if state != 'COMPLETE' and state != 'FAILED':
                     print(f"[CLEANUP] Marking run {rid} as FAILED")
                     mgr.transition_to("FAILED")
                 else:
                     print(f"[CLEANUP] Skipping {rid} (Terminal: {state})")
        except Exception as cleanup_err:
            print(f"[WARN] Failed to cleanup run {rid}: {cleanup_err}")

    # 3. Verify Final States
    print("\n>>> VERIFICATION")
    
    final_m1 = PipelineStateManager(r1)
    final_m2 = PipelineStateManager(r2)
    final_m3 = PipelineStateManager(r3)
    
    import json
    def get_state(mgr):
        with open(mgr.state_file, 'r') as f:
            return json.load(f)['current_state']

    v1 = get_state(final_m1)
    v2 = get_state(final_m2)
    v3 = get_state(final_m3)
    
    print(f"R1: {v1} (Expected: COMPLETE)")
    print(f"R2: {v2} (Expected: FAILED)")
    print(f"R3: {v3} (Expected: FAILED)")
    
    if v1 == "COMPLETE" and v2 == "FAILED" and v3 == "FAILED":
        print("SUCCESS: Cleanup logic validated.")
    else:
        print("FAILURE: State mismatch.")
        sys.exit(1)

if __name__ == "__main__":
    main()
