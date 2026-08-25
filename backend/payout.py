"""Ranked war paysheet math, reconstructed from the `Main` sheet's cell formulas.

war_pay        = cache_sell_price - total_expenses
pay_for_hits   = war_pay * (1 - leadership_cut_pct)
inside_pool    = pay_for_hits * inside_hits / total_hits
outside_pool   = pay_for_hits * (outside_hits + assist_hits) / total_hits
inside_pool   += outside_pool * (1 - outside_pay_rate)   # unpaid share of outside pool folds back in
outside_pool  *= outside_pay_rate
per_inside_hit_rate  = inside_pool / total_inside_hits
per_outside_hit_rate = outside_pool / total_outside_and_assist_hits

member_gross = inside_hits * per_inside_hit_rate + (outside_hits + assist_hits) * per_outside_hit_rate

Each xanax is expected to buy 10 hits (inside + outside + assist, rounded up - e.g. 11
hits covers 2 xanax). Any xanax used beyond what the member's hits cover is fined at
FINE_PER_UNPAID_XANAX, unless the member has paid it back (fine_waived).

member_final = (member_gross - applied_fine) * rank_pay_rate
"""

from dataclasses import dataclass, field

HITS_PER_XANAX = 10
FINE_PER_UNPAID_XANAX = 1_000_000


@dataclass
class MemberInput:
    member_id: int
    name: str
    inside_hits: int = 0
    outside_hits: int = 0
    assist_hits: int = 0
    xanax_used: int = 0
    fine_waived: bool = False
    pay_rank: str | None = None


@dataclass
class MemberResult:
    member_id: int
    name: str
    inside_hits: int
    outside_hits: int
    assist_hits: int
    xanax_used: int
    unpaid_xanax: int
    calculated_fine: float
    fine_waived: bool
    applied_fine: float
    pay_rank: str | None
    rank_pay_rate_pct: float
    pay_inside: float
    pay_outside: float
    gross_pay: float
    final_pay: float


@dataclass
class PaysheetResult:
    total_expenses: float
    war_pay: float
    pay_for_hits: float
    total_inside_hits: int
    total_outside_assist_hits: int
    per_inside_hit_rate: float
    per_outside_hit_rate: float
    members: list[MemberResult] = field(default_factory=list)


def compute_paysheet(
    cache_sell_price: float,
    expense_lines: list[dict],
    leadership_cut_pct: float,
    outside_pay_rate_pct: float,
    members: list[MemberInput],
    rank_pay_rates: dict[str, float],
) -> PaysheetResult:
    total_expenses = sum(line["amount"] for line in expense_lines)
    war_pay = cache_sell_price - total_expenses
    pay_for_hits = war_pay * (1 - leadership_cut_pct / 100)

    # Members on a 0%-rate rank (e.g. Leader) are paid via the flat leadership cut above,
    # not the per-hit pool - their hits are excluded so they don't dilute everyone else's rate.
    pool_members = [m for m in members if rank_pay_rates.get(m.pay_rank, 0.0) != 0]
    total_inside_hits = sum(m.inside_hits for m in pool_members)
    total_outside_assist_hits = sum(m.outside_hits + m.assist_hits for m in pool_members)
    total_hits = total_inside_hits + total_outside_assist_hits

    if total_hits > 0:
        inside_pool = pay_for_hits * total_inside_hits / total_hits
        outside_pool = pay_for_hits * total_outside_assist_hits / total_hits
    else:
        inside_pool = outside_pool = 0.0

    outside_rate = outside_pay_rate_pct / 100
    inside_pool_final = inside_pool + outside_pool * (1 - outside_rate)
    outside_pool_final = outside_pool * outside_rate

    per_inside_hit_rate = inside_pool_final / total_inside_hits if total_inside_hits else 0.0
    per_outside_hit_rate = (
        outside_pool_final / total_outside_assist_hits if total_outside_assist_hits else 0.0
    )

    member_results = []
    for m in members:
        pay_inside = m.inside_hits * per_inside_hit_rate
        pay_outside = (m.outside_hits + m.assist_hits) * per_outside_hit_rate
        gross_pay = pay_inside + pay_outside
        rank_rate_pct = rank_pay_rates.get(m.pay_rank, 0.0)

        total_member_hits = m.inside_hits + m.outside_hits + m.assist_hits
        xanax_covered = (total_member_hits + HITS_PER_XANAX - 1) // HITS_PER_XANAX
        unpaid_xanax = max(0, m.xanax_used - xanax_covered)
        calculated_fine = unpaid_xanax * FINE_PER_UNPAID_XANAX
        applied_fine = 0.0 if m.fine_waived else calculated_fine

        final_pay = (gross_pay - applied_fine) * (rank_rate_pct / 100)

        member_results.append(
            MemberResult(
                member_id=m.member_id,
                name=m.name,
                inside_hits=m.inside_hits,
                outside_hits=m.outside_hits,
                assist_hits=m.assist_hits,
                xanax_used=m.xanax_used,
                unpaid_xanax=unpaid_xanax,
                calculated_fine=calculated_fine,
                fine_waived=m.fine_waived,
                applied_fine=applied_fine,
                pay_rank=m.pay_rank,
                rank_pay_rate_pct=rank_rate_pct,
                pay_inside=pay_inside,
                pay_outside=pay_outside,
                gross_pay=gross_pay,
                final_pay=final_pay,
            )
        )

    return PaysheetResult(
        total_expenses=total_expenses,
        war_pay=war_pay,
        pay_for_hits=pay_for_hits,
        total_inside_hits=total_inside_hits,
        total_outside_assist_hits=total_outside_assist_hits,
        per_inside_hit_rate=per_inside_hit_rate,
        per_outside_hit_rate=per_outside_hit_rate,
        members=member_results,
    )
