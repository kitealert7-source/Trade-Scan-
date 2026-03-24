
import pandas as pd
from pathlib import Path
import shutil

def purge_run_id(run_id):
    file_path = Path("backtests/Strategy_Master_Filter.xlsx")
    if not file_path.exists():
        print("Master Filter not found.")
        return

    # Backup
    backup_path = file_path.with_suffix(".xlsx.bak")
    shutil.copy(file_path, backup_path)
    print(f"Backed up to {backup_path}")

    try:
        df = pd.read_excel(file_path)
        print(f"Original Row Count: {len(df)}")
        
        # Filter
        original_count = len(df)
        df_cleaned = df[df["run_id"] != run_id]
        new_count = len(df_cleaned)
        
        if original_count == new_count:
            print(f"Run ID {run_id} not found. No changes made.")
        else:
            temp_path = file_path.with_suffix(".xlsx.tmp")
            df_cleaned.to_excel(temp_path, index=False)
            print(f"Saved to temp file {temp_path}")
            
            try:
                shutil.move(temp_path, file_path)
                print("Replaced Master Filter with cleaned version.")
            except Exception as e:
                print(f"Failed to replace original file: {e}")
                print("Attempting delete and move...")
                try:
                    file_path.unlink()
                    shutil.move(temp_path, file_path)
                    print("Success (Delete+Move).")
                except Exception as e2:
                    print(f"Critical Failure: {e2}")
            
    except Exception as e:
        print(f"Error processing Excel: {e}")

if __name__ == "__main__":
    purge_run_id("c70fc8087d7a")
