import pandas as pd
from pathlib import Path

path = Path("backtests/Strategy_Master_Filter.xlsx")
if not path.exists():
    print("File not found")
else:
    try:
        df = pd.read_excel(path)
        print("Columns:", df.columns.tolist())
        print("Row Count:", len(df))
        if len(df) > 0:
            print("First Row:", df.iloc[0].to_dict())
            
            # Check dtypes
            print("\nrun_id values:")
            print(df["run_id"].head().tolist())
            print("strategy values:")
            print(df["strategy"].head().tolist())
    except Exception as e:
        print("Error:", e)
