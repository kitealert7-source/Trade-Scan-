import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.pipeline_utils import DirectiveStateManager

def reset_directive(directive_id):
    print(f"Resetting state for {directive_id}...")
    mgr = DirectiveStateManager(directive_id)
    
    current = mgr.get_state()
    print(f"Current State: {current}")
    
    if current == "INITIALIZED":
        print("Already INITIALIZED.")
        return

    # If COMPLETE, we need to fail it first? 
    # ALLOWED_TRANSITIONS: PORTFOLIO_COMPLETE -> FAILED by default logic?
    # Let's check ALLOWED_TRANSITIONS in class
    # "PORTFOLIO_COMPLETE": ["FAILED"] matches.
    
    if current == "PORTFOLIO_COMPLETE":
        print("Transitioning to FAILED...")
        try:
            mgr.transition_to("FAILED")
        except Exception as e:
            print(f"Error transitioning to FAILED (ignoring): {e}")

    # Now from FAILED (or other state), transition to INITIALIZED
    print("Transitioning to INITIALIZED...")
    mgr.transition_to("INITIALIZED")
    print("Reset Complete.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/reset_directive.py <DIRECTIVE_ID>")
        sys.exit(1)
    
    reset_directive(sys.argv[1])
