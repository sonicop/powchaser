import datetime
import pandas as pd
import requests
import streamlit as st

# Set page config
st.set_page_config(
    page_title="Ski Resort Powder Predictor", page_icon="⛷️", layout="wide"
)

# Pre-defined lists of resorts with lat/lon coordinates
RESORTS = {
    "Nearby Default (Washington Cascades)": [
        {"name": "Crystal Mountain Resort", "lat": 46.9356, "lon": -121.4745},
        {"name": "Mt. Baker Ski Area", "lat": 48.8579, "lon": -121.6606},
        {"name": "The Summit at Snoqualmie", "lat": 47.4253, "lon": -121.4138},
        {"name": "White Pass Ski Area", "lat": 46.6384, "lon": -121.3934},
        {"name": "Stevens Pass", "lat": 47.7447, "lon": -121.0905},
    ],
    "Custom Wishlist (Global Favorites)": [
        {"name": "Whistler Blackcomb", "lat": 50.1163, "lon": -122.9574},
        {"name": "Vail Ski Resort", "lat": 39.6403, "lon": -106.3742},
        {"name": "Jackson Hole", "lat": 43.5875, "lon": -110.8279},
        {"name": "Alta Ski Area", "lat": 40.5883, "lon": -111.6391},
    ],
}


@st.cache_data(ttl=3600)
def fetch_resort_weather(lat, lon):
    """Fetches past 7 days and tomorrow's forecast from Open-Meteo API in standard metric units."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,snowfall_sum,wind_gusts_10m_max,cloud_cover_mean"
        f"&past_days=7&forecast_days=2&timezone=auto"
    )

    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            daily = data.get("daily", {})
            df = pd.DataFrame({
                "date": daily.get("time", []),
                "temp_max": daily.get("temperature_2m_max", []),
                "temp_min": daily.get("temperature_2m_min", []),
                "snowfall_sum": daily.get("snowfall_sum", []),
                "wind_gust": daily.get("wind_gusts_10m_max", []),
                "cloud_cover": daily.get("cloud_cover_mean", []),
            })
            return df
    except Exception as e:
        print(f"Error fetching data: {e}")
    return None


def calculate_powder_score(df, is_imperial=True):
    """Calculates a 0-100 powder score and formats warnings in the chosen unit system."""
    if df is None or len(df) < 8:
        return 20, "Data error", []

    # Split history (past 7 days) and forecast (tomorrow is index 7)
    history = df.iloc[:-1]
    tomorrow = df.iloc[-1]

    score = 50
    warnings = []

    # 1. Snow Accumulation Factor (Last 48h vs older, calculated in cm)
    recent_snow = (
        df.iloc[-2]["snowfall_sum"] * 3
        + df.iloc[-3]["snowfall_sum"] * 1.5
        + history["snowfall_sum"].sum() * 0.2
    )
    score += min(30, recent_snow * 5)

    # 2. Freeze-Thaw Cycle Check (The Icy Crust Killer)
    freeze_thaw_count = 0
    for _, row in history.tail(5).iterrows():
        if row["temp_max"] > 2.0 and row["temp_min"] < 0:
            freeze_thaw_count += 1

    if freeze_thaw_count > 0:
        penalty = freeze_thaw_count * 12
        score -= penalty
        warnings.append(
            f"⚠️ Freeze-Thaw Risk: Detected {freeze_thaw_count} melt-freeze cycles"
            " recently (icy base risk)."
        )

    # 3. Wind Hold Risk Check for Tomorrow
    wind_gust_kmh = tomorrow["wind_gust"]
    if is_imperial:
        wind_display = f"{wind_gust_kmh * 0.621371:.1f} mph"
    else:
        wind_display = f"{wind_gust_kmh:.1f} km/h"

    if wind_gust_kmh > 65:  # ~40 mph
        score -= 25
        warnings.append(
            f"🔴 High Wind Hold Risk: Gusts expected at {wind_display}."
        )
    elif wind_gust_kmh > 50:  # ~31 mph
        score -= 10
        warnings.append(
            f"🟡 Moderate Wind Risk: Gusts expected at {wind_display}."
        )

    # Clamp score between 0 and 100
    final_score = max(5, min(100, int(score)))

    # Status Badge
    if final_score >= 70:
        status = "🟢 GO (Prime Powder)"
    elif final_score >= 40:
        status = "🟡 BORDERLINE (Variable Conditions)"
    else:
        status = "🔴 SKIP (Icy / Wind / Low Base)"

    return final_score, status, warnings


def format_raw_dataframe(df, is_imperial=True):
    """Converts and renames raw weather dataframe columns based on selected units."""
    display_df = df.copy()
    if is_imperial:
        display_df["temp_max"] = (display_df["temp_max"] * 9 / 5 + 32).round(1)
        display_df["temp_min"] = (display_df["temp_min"] * 9 / 5 + 32).round(1)
        display_df["snowfall_sum"] = (display_df["snowfall_sum"] * 0.393701).round(1)
        display_df["wind_gust"] = (display_df["wind_gust"] * 0.621371).round(1)
        return display_df.rename(
            columns={
                "date": "Date",
                "temp_max": "Max Temp (°F)",
                "temp_min": "Min Temp (°F)",
                "snowfall_sum": "Snowfall (in)",
                "wind_gust": "Max Wind Gust (mph)",
                "cloud_cover": "Cloud Cover (%)",
            }
        )
    else:
        return display_df.rename(
            columns={
                "date": "Date",
                "temp_max": "Max Temp (°C)",
                "temp_min": "Min Temp (°C)",
                "snowfall_sum": "Snowfall (cm)",
                "wind_gust": "Max Wind Gust (km/h)",
                "cloud_cover": "Cloud Cover (%)",
            }
        )


# --- UI LAYOUT ---
st.title("⛷️ Smart Ski Resort Powder Decision App")
st.markdown(
    "Evaluates the **past 7 days of weather history** (freeze-thaw cycles,"
    " base building) and **tomorrow's forecast** (wind holds, fresh snow) to"
    " rank where you should ski next."
)

# Sidebar controls
st.sidebar.header("Configuration")

unit_choice = st.sidebar.radio(
    "Measurement Units:",
    ["Imperial (°F, in, mph)", "Metric (°C, cm, km/h)"],
    index=0,  # Defaults to Imperial
)
is_imperial = unit_choice.startswith("Imperial")

selected_group = st.sidebar.radio(
    "Select Resort List:", list(RESORTS.keys())
)
resort_list = RESORTS[selected_group]

st.markdown("---")

# Process each resort
results = []
for resort in resort_list:
    df = fetch_resort_weather(resort["lat"], resort["lon"])
    score, status, warnings = calculate_powder_score(df, is_imperial=is_imperial)
    results.append({
        "name": resort["name"],
        "score": score,
        "status": status,
        "warnings": warnings,
        "raw_data": df,
    })

# Sort resorts by highest score
results = sorted(results, key=lambda x: x["score"], reverse=True)

# Render Resort Cards
for item in results:
    with st.container():
        col1, col2 = st.columns([3, 2])

        with col1:
            st.subheader(item["name"])
            st.markdown(f"**Status:** {item['status']}")
            if item["warnings"]:
                for w in item["warnings"]:
                    st.caption(w)
            else:
                st.caption("✅ Stable base and clean weather metrics.")

        with col2:
            st.metric(
                label="Calculated Powder Score", value=f"{item['score']} / 100"
            )

        # Expander for Raw Data Inspection
        with st.expander(
            f"📊 Inspect Raw Weather Data for {item['name']} (Past 7 Days + Forecast)"
        ):
            if item["raw_data"] is not None:
                formatted_df = format_raw_dataframe(
                    item["raw_data"], is_imperial=is_imperial
                )
                st.dataframe(formatted_df, use_container_width=True)
            else:
                st.error("Could not load raw data tables from API.")

        st.markdown("---")
