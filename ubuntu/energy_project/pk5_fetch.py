import pandas as pd
from datetime import datetime

print("[INFO] Start skryptu PK5")

# przykładowe dane testowe
df = pd.DataFrame({
    "timestamp": [datetime.now()],
    "value": [123]
})

# zapis
output_path = "pk5_test.parquet"
df.to_parquet(output_path, index=False)

print(f"[OK] Zapisano plik: {output_path}")
