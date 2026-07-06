from passfit.engine import PassOption


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
