"""같은 단지·같은 평형 비교 지수 (고정효과 회귀)

  ln(거래가) = 단지·평형 고유값 + 월 효과 + 오차
를 모든 거래로 한꺼번에 추정해 월 효과를 지수로 쓴다 (기준월 = 100).
- 같은 단지·평형 안의 모든 거래끼리 비교하는 것과 같아서, '바로 앞 거래와만 비교'하는 방식이
  같은 달 거래를 버리며 상승·하락 폭을 작게 잡던 문제가 없다.
- 두 달 이상에 걸쳐 거래된 단지·평형만 쓰인다 (한 달에만 거래된 곳은 비교 대상이 없음).
- 단지·평형 중위가에서 2배 넘게 벗어난 거래는 입력 오류·특수 거래로 보고 뺀다.
"""
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix, hstack
from scipy.sparse.linalg import lsqr

MAX_RATIO = 2.0


def fe_index(units, t, lnp, n_months):
    """units: 단지·평형 식별값, t: 월 번호(0 = 기준월), lnp: 로그 거래가
    반환: (지수 배열 길이 n_months, 쓰인 거래 수)"""
    d = pd.DataFrame({"u": pd.factorize(pd.Series(list(units)) if not isinstance(units, pd.Series) else units)[0],
                      "t": np.asarray(t, dtype=int), "y": np.asarray(lnp, dtype=float)})
    d = d[(d["y"] - d.groupby("u")["y"].transform("median")).abs() <= np.log(MAX_RATIO)]
    d = d[d.groupby("u")["t"].transform("nunique") >= 2]
    if d.empty:
        return np.full(n_months, np.nan), 0
    # 기준월(0)과 이어지지 않는 달은 계산할 수 없음: 같은 단지·평형으로 이어진 달끼리 묶어(union-find) 기준월과 다른 묶음이면 비움
    parent = list(range(n_months))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for ms in d.groupby("u")["t"].unique():
        r0 = find(int(ms[0]))
        for m_ in ms[1:]:
            parent[find(int(m_))] = r0
    linked = np.array([find(m_) == find(0) for m_ in range(n_months)])
    if not (d["t"] == 0).any():
        return np.full(n_months, np.nan), 0
    d = d[linked[d["t"].to_numpy()]]
    u = pd.factorize(d["u"])[0]
    n, k = len(d), u.max() + 1
    r = np.arange(n)
    U = coo_matrix((np.ones(n), (r, u)), shape=(n, k))
    m = d["t"].to_numpy()
    keep = m > 0
    M = coo_matrix((np.ones(keep.sum()), (r[keep], m[keep] - 1)), shape=(n, n_months - 1))
    sol = lsqr(hstack([U, M]).tocsr(), d["y"].to_numpy(), atol=1e-12, btol=1e-12, iter_lim=50000)[0]
    b = np.r_[0.0, sol[k:]]
    seen = (np.bincount(m, minlength=n_months) > 0) & linked
    b[~seen] = np.nan                       # 거래가 없거나 기준월과 이어지지 않는 달은 비움
    return np.exp(b) * 100, n
