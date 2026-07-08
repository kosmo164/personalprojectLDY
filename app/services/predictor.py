'''
- 역할 : 파이썬의 대표격인 머신러닝.데이터분석 라이브러리인 Scikit-learn(사이킷런)에서
    선형 회귀 모듈을 가져옴
- 의미 : 과거의 데이터를 바탕으로 데이터들을 가장 잘 대변하는 하나의 직잔하는 '추세선(직선)'
    을 그리기 위한 수학적 알고리즘 엔진을 탑재하는 것        
'''
from sklearn.linear_model import LinearRegression
'''
- 역할 : 오라클DB에 접근하는 전역 통신 모듈을 연결
- 의미 : 외귀 연산을 돌리려면 X축에 쓸 시간 데이터와 Y축에 쓸 주가 데이터가 필요하므로,
    DB에서 이를 안전하게 쿼리해오기 위해 연동
'''
from app.db import repository


def predict_future_prices(srtn_cd: str) -> dict:
    """단순 선형회귀로 3/6/12개월 뒤 가격의 등락률(%)을 추정."""
    try:
        df = repository.get_close_series_for_regression(srtn_cd)

        if len(df) < 30:
            return {"p_3m": 0, "p_6m": 0, "p_12m": 0}

        X = df["day_seq"].values.reshape(-1, 1)
        y = df["clpr"].values

        model = LinearRegression()
        model.fit(X, y)

        current_day = X[-1][0]
        current_price = y[-1]

        pred_3m = model.predict([[current_day + 90]])[0]
        pred_6m = model.predict([[current_day + 180]])[0]
        pred_12m = model.predict([[current_day + 365]])[0]

        return {
            "p_3m": round(((pred_3m - current_price) / current_price) * 100, 2),
            "p_6m": round(((pred_6m - current_price) / current_price) * 100, 2),
            "p_12m": round(((pred_12m - current_price) / current_price) * 100, 2),
        }
    except Exception as e:
        print(f"❌ 예측 연산 중 오류 발생 ({srtn_cd}): {str(e)}")
        return {"p_3m": 0, "p_6m": 0, "p_12m": 0}
