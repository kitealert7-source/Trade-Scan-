
import pandas as pd
import os

MASTER_SHEET = "backtests/Strategy_Master_Filter.xlsx"

def configure_portfolio():
    if not os.path.exists(MASTER_SHEET):
        print(f"Error: {MASTER_SHEET} not found.")
        return

    df = pd.read_excel(MASTER_SHEET)
    print("Columns:", df.columns.tolist())
    
    # Check if IN_PORTFOLIO exists, if not create it
    if 'IN_PORTFOLIO' not in df.columns:
        print("IN_PORTFOLIO column missing. Creating it (default False).")
        df['IN_PORTFOLIO'] = False

    # Filter for IDX28 runs
    # Assuming 'strategy' column holds 'IDX28' or we iterate by RunID match
    # Let's inspect unique strategies
    if 'strategy' in df.columns:
        # Use string conversion and startswith to match IDX28_...
        idx28_mask = df['strategy'].astype(str).str.startswith('IDX28')
        print(f"Found {idx28_mask.sum()} entries for IDX28.")
        
        # Set IN_PORTFOLIO = True for IDX28
        df.loc[idx28_mask, 'IN_PORTFOLIO'] = True
        print("Updated IN_PORTFOLIO flags for IDX28.")
    else:
        print("Strategy column not found!")

    # Save back to a temp file first
    temp_file = MASTER_SHEET.replace(".xlsx", "_TEMP.xlsx")
    df.to_excel(temp_file, index=False)
    print(f"Saved updates to {temp_file}")
    
    # Try to replace original
    try:
        # import os  <-- Removed to avoid UnboundLocalError
        if os.path.exists(MASTER_SHEET):
            os.remove(MASTER_SHEET)
        os.rename(temp_file, MASTER_SHEET)
        print(f"Successfully updated {MASTER_SHEET}")
    except PermissionError:
        print(f"COULD NOT REPLACE {MASTER_SHEET}. It might be open.")
        print(f"New data is in {temp_file}. Please close the file and try again.")
    except Exception as e:
        print(f"Error replacing file: {e}")

if __name__ == "__main__":
    configure_portfolio()
