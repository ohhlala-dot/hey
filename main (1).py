import json
import requests
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# ============================================================
# 1. 앱 기본 설정
# ============================================================
st.set_page_config(
    page_title="전국 고령화 단계구분도",
    page_icon="🗺️",
    layout="wide",
)

# 사용자가 지정한 원본 데이터 주소
POPULATION_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/"
    "contents//main/population_ts_yearly_gender.zip"
)
GEOJSON_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/"
    "contents//main/sigungu_kr.geojson"
)

# 따뜻한 색감의 화면 디자인
BG_COLOR = "#FFF9F2"
TEXT_COLOR = "#49382E"
BORDER_COLOR = "#E9D8C8"


st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {BG_COLOR};
        color: {TEXT_COLOR};
    }}
    h1, h2, h3 {{
        color: {TEXT_COLOR};
    }}
    div[data-testid="stMetric"] {{
        background-color: #FFFFFF;
        border: 1px solid {BORDER_COLOR};
        border-radius: 14px;
        padding: 14px;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 2. 데이터 다운로드 및 읽기
# ============================================================
@st.cache_data(show_spinner="인구 데이터와 시군구 경계를 불러오는 중입니다...")
def load_population_data():
    # URL의 ZIP 압축 CSV를 pandas로 읽습니다.
    population_df = pd.read_csv(
        POPULATION_URL,
        compression="zip",
        dtype={"코드": "string"},
    )

    # 열 이름의 앞뒤 공백을 정리합니다.
    population_df.columns = population_df.columns.astype(str).str.strip()

    # 연도는 숫자로 바꾼 뒤 2026년 데이터만 사용합니다.
    population_df["연도"] = pd.to_numeric(
        population_df["연도"], errors="coerce"
    )
    population_df = population_df[population_df["연도"] == 2026].copy()

    if population_df.empty:
        raise ValueError("인구 데이터에서 2026년 자료를 찾을 수 없습니다.")

    # 코드는 문자열로 유지하고, 앞의 0이 사라지지 않도록 합니다.
    population_df["코드"] = (
        population_df["코드"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(10)
    )

    # 인구 관련 열은 숫자로 변환합니다.
    population_columns = [
        col for col in population_df.columns
        if col.startswith(("계_", "남_", "여_"))
    ]
    for col in population_columns:
        population_df[col] = pd.to_numeric(
            population_df[col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        ).fillna(0)

    # requests로 GeoJSON을 내려받고 JSON으로 읽습니다.
    response = requests.get(GEOJSON_URL, timeout=60)
    response.raise_for_status()
    geojson_data = response.json()

    return population_df, geojson_data


# ============================================================
# 3. 고령화율 계산 및 시군구 코드 연결
# ============================================================
@st.cache_data(show_spinner=False)
def calculate_sigungu_aging(population_df):
    # 전체 인구는 '계_'로 시작하는 열만 합산합니다.
    # '남_'과 '여_' 열은 전체 인구에 중복해서 더하지 않습니다.
    total_columns = [
        col for col in population_df.columns
        if col.startswith("계_")
    ]

    # 65세 이상 인구는 계_65세부터 계_100세 이상까지 합산합니다.
    elderly_columns = [
        f"계_{age}세" for age in range(65, 100)
    ] + ["계_100세 이상"]

    missing_total = [
        col for col in total_columns if col not in population_df.columns
    ]
    missing_elderly = [
        col for col in elderly_columns if col not in population_df.columns
    ]

    if not total_columns:
        raise ValueError("'계_'로 시작하는 전체 인구 열을 찾지 못했습니다.")

    if missing_elderly:
        raise ValueError(
            "65세 이상 인구 열 일부를 찾지 못했습니다: "
            + ", ".join(missing_elderly[:8])
        )

    # 동 코드의 앞 5자리를 시군구 코드로 사용합니다.
    population_df = population_df.copy()
    population_df["시군구코드"] = population_df["코드"].str[:5]

    # 동별 행을 시군구 단위로 합산합니다.
    grouped = (
        population_df.groupby("시군구코드", as_index=False)[
            total_columns + elderly_columns
        ]
        .sum()
    )

    grouped["전체인구"] = grouped[total_columns].sum(axis=1)
    grouped["65세이상인구"] = grouped[elderly_columns].sum(axis=1)

    # 전체 인구가 0이면 나눗셈 오류 대신 고령화율을 결측값으로 둡니다.
    grouped["고령화율"] = np.where(
        grouped["전체인구"] > 0,
        grouped["65세이상인구"] / grouped["전체인구"] * 100,
        np.nan,
    )

    return grouped[[
        "시군구코드", "전체인구", "65세이상인구", "고령화율"
    ]]


# ============================================================
# 4. 앱 제목과 데이터 로딩
# ============================================================
st.title("🗺️ 전국 고령화 단계구분도")
st.write(
    "2026년 6월 기준 읍·면·동 인구를 시군구 단위로 합산해 "
    "65세 이상 인구 비율을 지도에 표시합니다."
)

try:
    population_df, geojson_data = load_population_data()
    aging_df = calculate_sigungu_aging(population_df)
except Exception as error:
    st.error(
        "데이터를 불러오거나 계산하는 중 문제가 발생했습니다. "
        "데이터 주소와 CSV 열 이름을 확인해 주세요."
    )
    st.exception(error)
    st.stop()


# ============================================================
# 5. GeoJSON의 시군구 코드와 인구 데이터 연결
# ============================================================
features = geojson_data.get("features", [])

if not features:
    st.error("GeoJSON에서 지도 경계(features)를 찾을 수 없습니다.")
    st.stop()

# 경계 속성의 코드도 문자열로 통일합니다.
# 이름이 아니라 코드로 조인하기 때문에 동명이인 지역 혼동을 줄입니다.
for feature in features:
    properties = feature.get("properties", {})
    code = properties.get("코드")

    if code is not None:
        code = str(code).strip()
        if code.endswith(".0"):
            code = code[:-2]
        properties["코드"] = code.zfill(5)

# GeoJSON 속성을 표 형태로 추출합니다.
boundary_rows = []
for feature in features:
    properties = feature.get("properties", {})
    code = properties.get("코드")

    if code is None:
        continue

    boundary_rows.append({
        "시군구코드": str(code).zfill(5),
        "시군구": properties.get("시군구", "이름 없음"),
        "시도": properties.get("시도", ""),
    })

boundary_df = pd.DataFrame(boundary_rows)

if boundary_df.empty:
    st.error("GeoJSON의 properties에서 '코드' 속성을 찾지 못했습니다.")
    st.stop()

# 코드 기준으로 결합합니다. 경계의 모든 지역을 유지합니다.
map_df = boundary_df.merge(
    aging_df,
    on="시군구코드",
    how="left",
    validate="many_to_one",
)

matched_count = int(map_df["고령화율"].notna().sum())
total_regions = len(map_df)

# 지도에 쓸 GeoJSON을 복사해 코드 속성을 확실히 문자열로 정리합니다.
# featureidkey는 properties.코드를 기준으로 위치를 맞춥니다.
map_geojson = {
    "type": geojson_data.get("type", "FeatureCollection"),
    "features": features,
}


# ============================================================
# 6. 주요 수치 카드
# ============================================================
valid_rates = map_df["고령화율"].dropna()
card1, card2, card3 = st.columns(3)

with card1:
    st.metric("지도 경계 시군구", f"{total_regions:,}곳")

with card2:
    st.metric("인구 자료 연결 성공", f"{matched_count:,}곳")

with card3:
    if not valid_rates.empty:
        st.metric("시군구 고령화율 평균", f"{valid_rates.mean():.1f}%")
    else:
        st.metric("시군구 고령화율 평균", "자료 없음")


# ============================================================
# 7. 고령화율 단계구분도
# ============================================================
st.subheader("65세 이상 인구 비율")

# 고령화율이 높을수록 연한 색에서 진한 주황·적갈색으로 표시합니다.
# 배경 타일 지도 없이 GeoJSON 경계만 그립니다.
fig = px.choropleth(
    map_df,
    geojson=map_geojson,
    locations="시군구코드",
    featureidkey="properties.코드",
    color="고령화율",
    color_continuous_scale=[
        [0.0, "#FFF1D6"],
        [0.25, "#F8C98B"],
        [0.50, "#E99A62"],
        [0.75, "#C96743"],
        [1.0, "#873D32"],
    ],
    hover_name="시군구",
    custom_data=["고령화율", "시도", "시군구코드"],
    labels={"고령화율": "65세 이상 비율"},
    title="전국 시군구별 고령화율 (2026년)",
)

# 마우스를 올리면 시군구 이름과 고령화율을 표시합니다.
fig.update_traces(
    hovertemplate=(
        "<b>%{hovertext}</b><br>"
        "고령화율: %{customdata[0]:.2f}%"
        "<extra></extra>"
    ),
    marker_line_color="#FFF9F2",
    marker_line_width=0.55,
    missing={"color": "#E8E2DC"},
)

# GeoJSON의 경계에 맞춰 지도를 확대하고 배경 지도는 숨깁니다.
fig.update_geos(
    fitbounds="locations",
    visible=False,
    showcountries=False,
    showcoastlines=False,
    showland=False,
    showlakes=False,
    showrivers=False,
    bgcolor=BG_COLOR,
)

fig.update_layout(
    paper_bgcolor=BG_COLOR,
    plot_bgcolor=BG_COLOR,
    font={"family": "Arial, sans-serif", "size": 13, "color": "#49382E"},
    margin={"l": 0, "r": 0, "t": 65, "b": 0},
    coloraxis_colorbar={
        "title": "고령화율 (%)",
        "ticksuffix": "%",
        "thickness": 18,
    },
    height=850,
)

st.plotly_chart(fig, use_container_width=True)

st.caption(
    "색이 진할수록 65세 이상 인구 비율이 높습니다. "
    "회색 지역은 인구 데이터와 연결되지 않았거나 고령화율을 계산할 수 없는 지역입니다."
)


# ============================================================
# 8. 연결 상태와 시군구별 수치 표
# ============================================================
with st.expander("📋 시군구별 고령화율 표 보기"):
    table_df = map_df[
        ["시도", "시군구", "시군구코드", "전체인구", "65세이상인구", "고령화율"]
    ].copy()

    table_df = table_df.rename(columns={
        "시도": "시도",
        "시군구": "시군구",
        "시군구코드": "시군구 코드",
        "전체인구": "전체 인구",
        "65세이상인구": "65세 이상 인구",
        "고령화율": "고령화율 (%)",
    })

    table_df["고령화율 (%)"] = table_df["고령화율 (%)"].round(2)
    table_df = table_df.sort_values(
        "고령화율 (%)", ascending=False, na_position="last"
    )

    st.dataframe(
        table_df,
        hide_index=True,
        use_container_width=True,
    )

st.markdown(
    """
    <div style="
        text-align:center;
        color:#8A7567;
        padding:20px 0 5px 0;
        font-size:13px;
    ">
        전국 고령화 단계구분도 · 2026년 기준
    </div>
    """,
    unsafe_allow_html=True,
)
