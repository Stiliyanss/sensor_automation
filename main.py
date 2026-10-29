import gspread
import matplotlib.pyplot as plt
import pandas as pd

# 1. Връзка с Google Sheets чрез Service Account
gc = gspread.service_account(filename="service_account.json")
# Отваряме spreadsheet файла по точното му име в Google Drive
sh = gc.open("Sleep monitoring data") 


def load(tab_name):
    rows = sh.worksheet(tab_name).get_all_values(
        value_render_option="UNFORMATTED_VALUE"
    )
    return pd.DataFrame(
        rows[1:], columns=[str(c).strip().lower() for c in rows[0]]
    )


# 2. Зареждане и тикове
env = load("env_raw")
env["timestamp"] = pd.to_datetime(
    pd.to_numeric(env["timestamp"], errors="coerce"),
    unit="D",
    origin="1899-12-30",
).dt.round("s")

for col in ["temperature", "humidity", "light"]:
    env[col] = pd.to_numeric(env[col], errors="coerce")

env = env.dropna(subset=["timestamp", "temperature", "humidity", "light"])

# 3. Почистване
START = pd.Timestamp("2026-10-09 13:50")
n0 = len(env)
env = env[env["timestamp"] >= START]
env = env[
    env["humidity"].between(20, 90) & env["temperature"].between(10, 35)
]
env = env.drop_duplicates("timestamp").sort_values("timestamp")
print(f"Оставени {len(env)} от {n0} реда след почистване.")

# 4. 5-минутни средни
env5 = (
    env.set_index("timestamp")[["temperature", "humidity", "light"]]
    .resample("5min")
    .mean()
    .reset_index()
)

# 5. Нощни часове (21:00 - 10:00)
h = env5["timestamp"].dt.hour
env5 = env5[(h >= 21) | (h < 10)].copy()
env5["night"] = (env5["timestamp"] - pd.Timedelta(hours=12)).dt.date

# 6. Статистика
LIGHT_THRESHOLD = 26
g = env5.groupby("night")

nightly = pd.DataFrame({
    "temp_mean": g["temperature"].mean(),
    "temp_min": g["temperature"].min(),
    "temp_max": g["temperature"].max(),
    "hum_mean": g["humidity"].mean(),
    "bright_min": g["light"].apply(lambda s: (s < LIGHT_THRESHOLD).sum() * 5),
    "out_of_range_min": g["temperature"].apply(
        lambda s: ((s < 17) | (s > 20)).sum() * 5
    ),
    "missing_min": g["temperature"].apply(lambda s: s.isna().sum() * 5),
}).reset_index()

print("\nResults:")
print(nightly)

# 7. Запис в листа "presentable"
nightly["night"] = nightly["night"].astype(str)
values = (
    nightly.round(2).astype(object).where(nightly.notna(), "").values.tolist()
)

try:
    ws = sh.worksheet("presentable")
except gspread.WorksheetNotFound:
    ws = sh.add_worksheet("presentable", rows=100, cols=20)

ws.clear()
ws.update([nightly.columns.tolist()] + values)
print("The data was successfuly sent to 'presentable'!")