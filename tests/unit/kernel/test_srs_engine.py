"""Unit tests for SRSEngine SuperMemo SM-2 interval and ease factor calculations."""

from agent_os.kernel.srs_engine import SRSEngine


def test_srs_failure_resets_repetitions() -> None:
    """Pass grade 2; assert new_repetitions == 0 and new_interval_days == 1."""
    new_repetitions, new_interval_days, new_ease_factor = SRSEngine.calculate_sm2(
        grade=2,
        repetitions=4,
        interval_days=15,
        ease_factor=2.5,
    )
    assert new_repetitions == 0
    assert new_interval_days == 1
    assert new_ease_factor < 2.5


def test_srs_consecutive_success_progression() -> None:
    """Simulate grades [4, 5, 5]; assert intervals progress from 1 to 6 to >=15 days."""
    rep, ivl, ef = 0, 1, 2.5

    # First review: Grade 4 -> initial interval 1 day
    rep, ivl, ef = SRSEngine.calculate_sm2(4, rep, ivl, ef)
    assert rep == 1
    assert ivl == 1
    assert ef == 2.5

    # Second review: Grade 5 -> interval jumps to 6 days
    rep, ivl, ef = SRSEngine.calculate_sm2(5, rep, ivl, ef)
    assert rep == 2
    assert ivl == 6
    assert ef == 2.6

    # Third review: Grade 5 -> interval scales by ease factor (6 * 2.6 = ~16 days)
    rep, ivl, ef = SRSEngine.calculate_sm2(5, rep, ivl, ef)
    assert rep == 3
    assert ivl >= 15
    assert ef == 2.7


def test_srs_ease_factor_floor() -> None:
    """Pass repeated low passing or failing grades; assert ease factor never drops below 1.3."""
    rep, ivl, ef = 0, 1, 2.5
    for _ in range(20):
        rep, ivl, ef = SRSEngine.calculate_sm2(
            grade=1,
            repetitions=rep,
            interval_days=ivl,
            ease_factor=ef,
        )

    assert ef == 1.3
    assert ef >= 1.3
