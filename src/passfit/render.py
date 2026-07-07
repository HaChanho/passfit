from passfit.engine import PassOption


CAT_KO = {"general": "일반", "youth": "청년", "senior": "어르신",
          "multi_child_2": "2자녀", "multi_child_3": "3자녀+", "low_income": "저소득"}


def _rates_line(rates: dict) -> str:
    order = ["general", "youth", "senior", "multi_child_2", "multi_child_3", "low_income"]
    return ", ".join(f"{CAT_KO[k]} {rates[k]:.0%}" for k in order if k in rates)


def _pending_line(pending: list[str]) -> str:
    return "예정 혜택(미확정, 계산 미반영): " + ", ".join(pending) if pending else ""


def _sources(p: dict) -> str:
    return "\n".join(f"- {s['url']}" for s in p["sources"])


def render_pass_details(p: dict, base: dict | None = None) -> str:
    """서술형 상세 렌더. modu-card/legacy/plus/dongbaek/eung 각각 커스텀."""
    pid = p["id"]

    if pid == "modu-card":
        e = p["eligibility"]; c = p["conditions"]; y = p["youth_age"]
        overrides = p.get("regional_overrides", {})
        override_lines = []
        for sido, ov in overrides.items():
            parts = []
            if "youth_age_max" in ov:
                parts.append(f"청년 {y['min']}~{ov['youth_age_max']}세 확대")
            for k, v in ov.get("rate_overrides", {}).items():
                parts.append(f"{CAT_KO.get(k, k)} {v:.0%}")
            if parts:
                override_lines.append(f"  - **{sido}**: {', '.join(parts)}")
        override_block = "\n".join(override_lines)
        temp = ", ".join(f"{b['id']} ({b['valid_from']}~{b['valid_until']})"
                          for b in p.get("temporary_benefits", []))
        return (
            f"## {p['name']}\n"
            f"전국 어디서나 신청 가능한 대중교통 환급 카드입니다 "
            f"(운영: {p['operator']}).\n\n"
            f"**자격**: 만 {e['age_min']}세 이상, 거주지 무관.\n\n"
            f"**환급률(정률형)**: {_rates_line(p['rebate_rates'])}\n"
            f"  - 청년 기본: {y['min']}~{y['max']}세 (경기·인천·광주·울산·경남은 39세까지 확대)\n"
            f"  - 어르신: {p['senior_age_min']}세 이상\n\n"
            f"**정액형 기준금액** — 월 정액을 넘어선 지출을 환급 "
            f"(일반형/플러스형 2단계, 지역 티어·유형별 상이).\n\n"
            f"**최소 이용**: 월 {c['min_rides_month']}회 "
            f"(가입 첫 달은 예외 — 첫 달 예외 적용).\n\n"
            f"**한시 혜택**: {temp} — 정액 기준금액 반값 + 시차시간 승차 +30%p.\n\n"
            f"**지역 상향 혜택**:\n{override_block}\n\n"
            f"**미적용 수단**: {', '.join(p['excluded'])}\n\n"
            f"**출처**:\n{_sources(p)}"
        )

    if pid == "climate-card-legacy":
        variant_ko = {"transit-only": "대중교통 전용", "transit-bike": "따릉이 포함"}
        mode_ko = {"metropolitan_bus": "광역버스", "gtx": "GTX",
                   "shinbundang": "신분당선"}
        prices = ", ".join(f"{variant_ko.get(v['id'], v['id'])} {v['price']:,}원({v['duration_days']}일)"
                           for v in p["variants"])
        excl = ", ".join(mode_ko.get(m, m) for m in p["excluded_modes"])
        return (
            f"## {p['name']}\n"
            f"서울시가 운영하는 정액제 무제한 승차권입니다. "
            f"⚠️ **종료 예정** — {p['transition_note']}\n\n"
            f"**이용 대상**: 거주지 무관, 서울권 이용자.\n"
            f"**요금제**: {prices}\n"
            f"**포함 수단**: {p['included_scope']}\n"
            f"**제외 수단**: {excl} (별도 결제 필요)\n\n"
            f"**충전·유효 종료**:\n"
            f"  - 선불: {p['prepaid_charge_until']}까지 충전, {p['prepaid_valid_until']}까지 이용\n"
            f"  - 후불(기존 보유자만): {p['postpaid']['valid_until']}까지\n\n"
            f"**출처**:\n{_sources(p)}"
        )

    if pid == "climate-card-plus":
        assert base is not None, "climate-card-plus needs base for details"
        return (
            f"## {p['name']}\n"
            f"서울시가 대광위와 협력해 '{base['name']}'를 서울 브랜드로 재포장한 상품입니다. "
            f"**계산·환급은 모두의카드와 동일**하게 처리됩니다.\n\n"
            f"**대상**: 서울 거주자 (서울에서는 이 이름으로 발급·이용).\n"
            f"**{_pending_line(p['pending_benefits'])}**\n\n"
            f"---\n\n"
            f"### 기반 제도 — {base['name']}\n"
            + render_pass_details(base).split("\n", 1)[1]
        )

    if pid == "dongbaek-pass":
        e = p["eligibility"]
        return (
            f"## {p['name']}\n"
            f"부산시가 운영하는 **월 임계 초과분 환급** 방식의 지역 패스입니다. "
            f"모두의카드와 병용해도 유리한 금액이 자동 적용됩니다.\n\n"
            f"**자격**: 부산 거주자, 만 {e['age_min']}세 이상.\n"
            f"**작동 방식**: 월 대중교통 이용액이 {p['threshold']:,}원을 넘으면 초과분을 환급.\n\n"
            f"**적용 범위**: {p['scope_note']}\n\n"
            f"**참고**: {p['note']}\n\n"
            f"**출처**:\n{_sources(p)}"
        )

    if pid == "eung-pass":
        e = p["eligibility"]
        return (
            f"## {p['name']}\n"
            f"세종시가 운영하는 **선불 정액형** 지역 패스입니다.\n\n"
            f"**자격**: 세종 거주자, 만 {e['age_min']}세 이상 "
            f"(청소년 13~18세·70세 이상·장애인은 이용료 면제).\n"
            f"**작동 방식**: 월 {p['monthly_price']:,}원을 미리 결제하면 "
            f"월 {p['monthly_cap']:,}원까지 대중교통비를 커버.\n\n"
            f"**적용 범위**: {p['scope_note']}\n\n"
            f"**참고**: {p['note']}\n\n"
            f"**출처**:\n{_sources(p)}"
        )

    raise ValueError(f"unsupported pass_id: {pid}")


def render_comparison(opts: list[PassOption], region_note: str, notices: list[str],
                      caveats: list[str], detail: str, last_verified: str) -> str:
    if not opts:
        return "비교 가능한 패스가 없습니다. 거주 지역을 알려주시면 다시 확인할게요."
    best = opts[0]
    lines = [f"**결론: {best.name}({best.label})이 월 실질 부담 {best.net_cost:,}원으로 가장 유리합니다"
             f" (월 환급 {best.rebate:,}원).**", "", region_note, "",
             "| 선택지 | 월 환급 | 월 실질 부담 | 비고 |", "|---|---:|---:|---|"]
    for o in opts:
        lines.append(f"| {o.name} — {o.label} | {o.rebate:,}원 | {o.net_cost:,}원 | {o.note} |")
    warnings = [w for o in opts for w in o.warnings] + caveats
    if warnings:
        lines += ["", "**주의:**"] + [f"- {w}" for w in dict.fromkeys(warnings)]
    if notices:
        lines += ["", "**참고:**"] + [f"- {n}" for n in notices]
    if detail == "detailed":
        srcs = sorted({s for o in opts for s in o.sources})
        lines += ["", "**출처:**"] + [f"- {s}" for s in srcs]
    else:
        lines += ["", f"_출처: korea-pass.kr 등 공식 자료 ({last_verified} 확인 기준)_"]
    return "\n".join(lines)
