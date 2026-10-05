"""SuperMemo SM-2 spaced repetition calculation engine."""


class SRSEngine:
    """Spaced Repetition System calculation engine implementing SuperMemo SM-2."""

    @staticmethod
    def calculate_sm2(
        grade: int,
        repetitions: int,
        interval_days: int,
        ease_factor: float,
    ) -> tuple[int, int, float]:
        """Compute the next repetition count, interval (in days), and ease factor.

        Args:
            grade: Quality assessment grade between 0 (complete blackout) and 5 (perfect recall).
            repetitions: Consecutive successful recall attempts.
            interval_days: Prior review interval in days.
            ease_factor: Easiness factor multiplier, minimum 1.3.

        Returns:
            Tuple of (new_repetitions, new_interval_days, new_ease_factor).
        """
        clamped_grade = max(0, min(5, grade))

        if clamped_grade < 3:
            new_repetitions = 0
            new_interval_days = 1
        else:
            if repetitions == 0:
                new_interval_days = 1
            elif repetitions == 1:
                new_interval_days = 6
            else:
                new_interval_days = round(interval_days * ease_factor)
            new_repetitions = repetitions + 1

        ef_adjustment = 0.1 - (5 - clamped_grade) * (0.08 + (5 - clamped_grade) * 0.02)
        ef_prime = ease_factor + ef_adjustment
        new_ease_factor = max(1.3, round(ef_prime, 2))

        return new_repetitions, new_interval_days, new_ease_factor
