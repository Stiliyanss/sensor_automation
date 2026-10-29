import gspread
import pandas as pd

# 1. Връзка с Google Sheets
gc = gspread.service_account(filename="service_account.json")
sh = gc.open("Sleep monitoring data")

# Персонализирани прагове
IDEAL_TEMP_MIN = 19.0
IDEAL_TEMP_MAX = 22.0
IDEAL_HUM_MIN = 40.0
IDEAL_HUM_MAX = 60.0
LIGHT_THRESHOLD = 26.0

def load(tab_name):
    rows = sh.worksheet(tab_name).get_all_values(
        value_render_option="UNFORMATTED_VALUE"
    )
    # Превръщаме заглавията в малки букви и премахваме интервалите
    headers = [str(c).strip().lower() for c in rows[0]]
    df = pd.DataFrame(rows[1:], columns=headers)
    return df

# 2. Зареждане
env = load("env_raw")
print("Първоначални колони в env_raw:", env.columns.tolist())
print("Брой сурови редове:", len(env))

# Намираме коя колона отговаря на timestamp, temperature, humidity, light, led
# (ако заглавията са с главни букви или различни)
ts_col = next((c for c in env.columns if 'time' in c), env.columns[0])
temp_col = next((c for c in env.columns if 'temp' in c), 'temperature')
hum_col = next((c for c in env.columns if 'hum' in c), 'humidity')
light_col = next((c for c in env.columns if 'light' in c or 'bright' in c), 'light')
led_col = next((c for c in env.columns if 'led' in c), None)

# Преобразуване на датата
env["timestamp"] = pd.to_datetime(
    env[ts_col].astype(str).str.strip(), 
    dayfirst=True, 
    errors="coerce"
)

# Конвертиране на числените колони
for c_src, name in [(temp_col, "temperature"), (hum_col, "humidity"), (light_col, "light")]:
    if c_src in env.columns:
        env[name] = (
            env[c_src]
            .astype(str)
            .str.replace(",", ".")
            .pipe(pd.to_numeric, errors="coerce")
        )

if led_col and led_col in env.columns:
    env["led_is_on"] = env[led_col].astype(str).str.upper().isin(["ON", "1", "TRUE", "YES"])
else:
    env["led_is_on"] = False

# Почистване
env = env.dropna(subset=["timestamp", "temperature"])
n0 = len(env)
env = env.drop_duplicates("timestamp").sort_values("timestamp")
print(f"Оставени {len(env)} от {n0} реда след почистване.")

if len(env) == 0:
    print("Внимание: Все още няма намерени валидни данни. Проверете имената на колоните в Google Sheets.")
else:
    # 4. Resampling на 5-минутни интервали
    env5 = (
        env.set_index("timestamp")[["temperature", "humidity", "light", "led_is_on"]]
        .resample("5min")
        .agg({
            "temperature": "mean",
            "humidity": "mean",
            "light": "mean",
            "led_is_on": "any"
        })
        .reset_index()
    )

    env5["date"] = env5["timestamp"].dt.date

    # 5. Групиране и статистики
    g = env5.groupby("date")

    stats = pd.DataFrame({
        "temp_mean": g["temperature"].mean(),
        "temp_min": g["temperature"].min(),
        "temp_max": g["temperature"].max(),
        "temp_stability_std": g["temperature"].std(),
        "hum_mean": g["humidity"].mean(),
        "comfort_score_pct": g.apply(
            lambda df: (
                ((df["temperature"].between(IDEAL_TEMP_MIN, IDEAL_TEMP_MAX)) & 
                 (df["humidity"].between(IDEAL_HUM_MIN, IDEAL_HUM_MAX))).sum() / len(df) * 100
            ) if len(df) > 0 else 0
        ),
        "out_of_comfort_min": g["temperature"].apply(
            lambda s: ((s < IDEAL_TEMP_MIN) | (s > IDEAL_TEMP_MAX)).sum() * 5
        ),
        "darkness_min": g["light"].apply(lambda s: (s < LIGHT_THRESHOLD).sum() * 5),
        "led_on_min": g["led_is_on"].apply(lambda val: val.sum() * 5 if hasattr(val, 'sum') else 0),
    }).reset_index()

    stats = stats.dropna(subset=["temp_mean"])
    print("\nРезултати:")
    print(stats)

    # 6. Запис в листа "presentable"
    stats["date"] = stats["date"].astype(str)
    values = (
        stats.round(2).astype(object).where(stats.notna(), "").values.tolist()
    )

    try:
        ws = sh.worksheet("presentable")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("presentable", rows=100, cols=20)

    ws.clear()
    ws.update([stats.columns.tolist()] + values)
    print("Данните бяха успешно записани в 'presentable'!")