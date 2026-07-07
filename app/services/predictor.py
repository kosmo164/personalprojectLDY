from sklearn.linear_model import LinearRegression
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
