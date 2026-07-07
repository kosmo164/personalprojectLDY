from app.db import repository


def recompute_all_indicators():
    """전 종목의 20일 이동평균 + 볼린저 밴드를 한 번의 SQL로 재계산."""
    try:
        updated = repository.recompute_all_indicators()
        print(f"✅ 전 종목 지표(이동평균/볼린저) 일괄 재계산 완료 ({updated}행)")
        return updated
    except Exception as e:
        print(f"❌ 지표 일괄 재계산 오류: {str(e)}")
        return 0
