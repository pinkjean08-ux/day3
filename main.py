"""
한강공원 주차장 월별 이용 현황 대시보드
서울 열린데이터광장 API: TbUseMonthstatusView

⚠️ 단위 참고
API 필드명은 UTZTN_HR(시간을 암시)이지만, 원본 값과 주차대수를 비교해보면
실제로는 '분' 단위 누적치로 판단됩니다. (예: 대당 값이 시간 기준으로는
한 달 최대 720시간을 초과하는 등 비현실적인 값이 나옴 → 분으로 환산하면
대당 평균 2~4시간대로 합리적인 범위가 됨) 이에 따라 이 앱은 원본 값을
'분'으로 간주하고, 필요한 곳에서 시간 단위로 환산해 표시합니다.
"""

import streamlit as st
import pandas as pd
import requests
import time

# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(
    page_title="한강공원 주차장 월별 이용 현황",
    page_icon="🌊",
    layout="wide",
)

SERVICE = "TbUseMonthstatusView"
BASE_URL = "http://openapi.seoul.go.kr:8088"
CHUNK_SIZE = 1000  # 서울시 API는 한 번에 최대 1000건까지 요청 가능


# -----------------------------
# 인증키 확보 (secrets 우선, 없으면 사용자 입력)
# -----------------------------
def get_api_key() -> str:
    key_from_secrets = st.secrets.get("SEOUL_API_KEY", "") if hasattr(st, "secrets") else ""
    if key_from_secrets:
        return key_from_secrets

    with st.sidebar:
        st.markdown("### 🔑 인증키 설정")
        st.caption("`.streamlit/secrets.toml`에 `SEOUL_API_KEY`가 없어 직접 입력이 필요합니다.")
        return st.text_input("서울 열린데이터광장 인증키", type="password")


# -----------------------------
# API 호출 (전체 페이지네이션 처리 + 캐싱)
# -----------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_data(api_key: str) -> pd.DataFrame:
    if not api_key:
        return pd.DataFrame()

    all_rows = []
    start = 1
    total_count = None

    while True:
        end = start + CHUNK_SIZE - 1
        url = f"{BASE_URL}/{api_key}/json/{SERVICE}/{start}/{end}/"

        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        body = data.get(SERVICE)
        if body is None:
            # 인증키 오류 등, 최상위에 RESULT만 오는 경우 처리
            result = data.get("RESULT", {})
            code = result.get("CODE", "UNKNOWN")
            message = result.get("MESSAGE", "알 수 없는 오류입니다.")
            raise RuntimeError(f"[{code}] {message}")

        result = body.get("RESULT", {})
        code = result.get("CODE", "")
        if code not in ("INFO-000",):
            message = result.get("MESSAGE", "알 수 없는 오류입니다.")
            if code == "INFO-200":
                break  # 더 이상 데이터 없음
            raise RuntimeError(f"[{code}] {message}")

        if total_count is None:
            total_count = int(body.get("list_total_count", 0))

        rows = body.get("row", [])
        all_rows.extend(rows)

        if end >= total_count or not rows:
            break
        start = end + 1
        time.sleep(0.05)  # 과도한 연속 호출 방지

    df = pd.DataFrame(all_rows)
    if df.empty:
        return df

    # 타입 정리
    df["PRK_CNTOM"] = pd.to_numeric(df["PRK_CNTOM"], errors="coerce")
    df["UTZTN_HR"] = pd.to_numeric(df["UTZTN_HR"], errors="coerce")
    df["연월"] = pd.to_datetime(df["DT"].str.replace("/", "-"), format="%Y-%m", errors="coerce")
    df["연도"] = df["연월"].dt.year
    df["월"] = df["연월"].dt.month
    df = df.rename(
        columns={
            "DSTRCT_TYPE": "지구코드",
            "PKLT_NM": "주차장명",
            "PRK_CNTOM": "주차대수",
            "UTZTN_HR": "이용시간(분)",
        }
    )
    # 시간 단위 환산 컬럼 추가 (분 -> 시간)
    df["이용시간(시간)"] = df["이용시간(분)"] / 60
    return df.dropna(subset=["연월"])


def format_hm(total_minutes: float) -> str:
    """분 단위 값을 'H시간 M분' 형태 문자열로 변환"""
    if pd.isna(total_minutes):
        return "-"
    hours = int(total_minutes // 60)
    minutes = int(round(total_minutes % 60))
    return f"{hours:,}시간 {minutes}분"


# -----------------------------
# 메인
# -----------------------------
def main():
    st.title("🌊 한강공원 주차장 월별 이용 현황")
    st.caption("데이터 출처: 서울 열린데이터광장 · TbUseMonthstatusView (미래한강본부 공원부 공원시설과)")
    st.caption(
        "⚠️ 원본 API 필드명은 `UTZTN_HR`(시간을 암시)이지만, 주차대수 대비 값을 검증한 결과 "
        "실제로는 **분 단위** 누적치로 판단되어 이 앱에서는 분을 기준으로 계산하고 있습니다."
    )

    api_key = get_api_key()

    if not api_key:
        st.info("좌측 사이드바에 서울 열린데이터광장 인증키를 입력하면 데이터를 불러옵니다.")
        st.stop()

    with st.spinner("데이터를 불러오는 중입니다..."):
        try:
            df = fetch_all_data(api_key)
        except RuntimeError as e:
            st.error(f"API 오류: {e}")
            st.stop()
        except requests.RequestException as e:
            st.error(f"네트워크 오류가 발생했습니다: {e}")
            st.stop()

    if df.empty:
        st.warning("조회된 데이터가 없습니다.")
        st.stop()

    # -----------------------------
    # 사이드바 필터
    # -----------------------------
    st.sidebar.markdown("### 🔎 필터")

    min_date, max_date = df["연월"].min(), df["연월"].max()
    date_range = st.sidebar.slider(
        "조회 기간",
        min_value=min_date.to_pydatetime(),
        max_value=max_date.to_pydatetime(),
        value=(min_date.to_pydatetime(), max_date.to_pydatetime()),
        format="YYYY/MM",
    )

    parking_lots = sorted(df["주차장명"].dropna().unique())
    selected_lots = st.sidebar.multiselect(
        "주차장 선택 (미선택 시 전체)", parking_lots, default=[]
    )

    st.sidebar.markdown(f"---\n총 **{len(df):,}**건의 데이터 (최근 갱신: {max_date:%Y-%m})")

    # 필터 적용
    filtered = df[(df["연월"] >= date_range[0]) & (df["연월"] <= date_range[1])]
    if selected_lots:
        filtered = filtered[filtered["주차장명"].isin(selected_lots)]

    if filtered.empty:
        st.warning("선택한 조건에 해당하는 데이터가 없습니다.")
        st.stop()

    # -----------------------------
    # 요약 지표
    # -----------------------------
    total_minutes = filtered["이용시간(분)"].sum()
    total_cars = filtered["주차대수"].sum()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 주차대수", f"{int(total_cars):,} 대")
    col2.metric("총 이용시간", f"{total_minutes / 60:,.0f} 시간")
    col3.metric("대상 주차장 수", f"{filtered['주차장명'].nunique()} 개")
    avg_minutes_per_car = total_minutes / max(total_cars, 1)
    col4.metric("대당 평균 이용시간", format_hm(avg_minutes_per_car))

    st.divider()

    # -----------------------------
    # 월별 추이
    # -----------------------------
    st.subheader("📈 월별 이용 추이")
    metric_choice = st.radio(
        "지표 선택", ["이용시간(시간)", "주차대수"], horizontal=True, key="trend_metric"
    )

    if selected_lots:
        trend = (
            filtered.groupby(["연월", "주차장명"])[metric_choice]
            .sum()
            .reset_index()
            .pivot(index="연월", columns="주차장명", values=metric_choice)
        )
    else:
        trend = filtered.groupby("연월")[metric_choice].sum()

    unit_label = "시간" if metric_choice == "이용시간(시간)" else "대"
    st.caption(f"단위: {unit_label}")
    st.line_chart(trend)

    # -----------------------------
    # 주차장별 순위
    # -----------------------------
    st.subheader("🏆 주차장별 이용 순위 (선택 기간 합계)")
    rank_metric = st.radio(
        "순위 기준", ["이용시간(시간)", "주차대수"], horizontal=True, key="rank_metric"
    )
    rank_df = (
        filtered.groupby("주차장명")[rank_metric]
        .sum()
        .sort_values(ascending=False)
        .head(15)
    )
    rank_unit_label = "시간" if rank_metric == "이용시간(시간)" else "대"
    st.caption(f"단위: {rank_unit_label}")
    st.bar_chart(rank_df)

    # -----------------------------
    # 원본 데이터 테이블 + 다운로드
    # -----------------------------
    st.subheader("📋 상세 데이터")
    display_cols = ["연월", "지구코드", "주차장명", "주차대수", "이용시간(분)", "이용시간(시간)"]
    show_df = filtered[display_cols].copy()
    show_df["이용시간(시간)"] = show_df["이용시간(시간)"].round(1)
    show_df = show_df.sort_values("연월", ascending=False)
    st.dataframe(show_df, use_container_width=True, hide_index=True)

    csv = show_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "CSV 다운로드",
        data=csv,
        file_name="hangang_parking_monthly.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
