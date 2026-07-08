'''
- from app.db : 프로젝트 내부 구조에서 데이터베이스 접근을 담당하는 패키지인 app/db 폴더를 가리킴.
- import repository : 해당 폴더 내의 repository.py 모듈을 가져옴
- 의미 : 이 서비스 코드는 데이터베이스에 직접 연결하거나 SQL 문을 내포하지 않음. 오직 데이터 접근을 전담하는 
    repository 객체에서 "DB안의 지표들을 다시 계산해줘"라고 위임하기 위해 가져온 것
'''
from app.db import repository

'''
- 이 함수는 파라미터(매개변수)를 받지 않음. 특정 종목 하나만 계산하는 것이 아니라, 데이터베이스에 존재하는 
    '모든 종목의 전체 기간 데이터'를 대상으로 지표를 한 번에 연산하돌고 설계되었기 때문임
'''
def recompute_all_indicators():
    """전 종목의 20일 이동평균 + 볼린저 밴드를 한 번의 SQL로 재계산."""
    '''
    안정성을 위한 예외처리패턴(try...except)
    - try블록 : 실행해야할 핵심 로직이 들어감. reposittory.recompute_all_indicators()를 호출하여 오라클 
        데이터베이스 내부에서 윈도우 함수(AVG() OVER, STDDEV() OVER)가 포함된 대형 MERGE INTO 쿼리를 실행
        하도록 명령함.
    - updated변수 : DB에서 실제로 지표가 계산되어 수정(Update)된 총 행(Row)수가 저장됨
    - 성공 로그 및 반환 : 콘솔창에 성공메시지와 함께 몇 건의 데이터가 갱신되었는지 출력(print)한 후, 수정된 
        행 수를 반환     
    '''
    try:
        updated = repository.recompute_all_indicators()
        print(f"✅ 전 종목 지표(이동평균/볼린저) 일괄 재계산 완료 ({updated}행)")
        return updated
    # except Exception as e : DB연결이 끊어지거나 SQL문법에러, 혹은 락(Lock)충동 등 try블록 안에서 어떤
    # 종류의 치명적인 오류가 발생하더라도 프로그램이 웹서버가 통째로 다운(Crash)되지 않도록 잡아주는 안전망
    
    # 실패 로그 및 반환 : 에러 내용(str(e))을 콘솔에 안전하게 출력한 뒤, 아무런 행도 업데이트되지 않았다는
    # 의미로 0을 반환하며 함수를 안전하게 종료함.
    except Exception as e:
        print(f"❌ 지표 일괄 재계산 오류: {str(e)}")
        return 0

'''
아키텍처 관점
- 해당 코드가 굳이 repository에 있는 기능을 한 번 더 감싸서 함수로 만든 이유는 역할 분담(Separation of Concerns)
    때문임
1. 레포지토리 계층(repository) : 오직 오라클DB와 대화하며 데이터를 가져오고 쿼리를 실행하는 물리적인 일만 함.
    에러가 나면 상위계층으로 에러를 던짐.
2. 서비스 계층(현재 코드) : 레포지토리가 던진 에러를 잡아내서 로그를 남기고, 성공/실패 여부를 판단하여 안전한 값
    (update 수치 또는 0)으로 가공함
3. 컨트롤러/라우터 계층(Flask API) : 이 서비스 함수를 호출하여 리턴된 숫자가 0보다 크면 화면에 "성공", 0이면 "실패"
    라는 JSON응답을 브라우저에 내려줌                  
'''


