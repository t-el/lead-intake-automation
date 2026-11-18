import pytest

from lead_intake.retry import PermanentError, TransientError, backoff_delay, retry_call


def test_retries_transient_then_succeeds():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TransientError("timeout")
        return "ok"

    assert retry_call(flaky, attempts=4, base_delay=1, sleep=sleeps.append) == "ok"
    assert len(calls) == 3 and len(sleeps) == 2
    assert sleeps[1] > sleeps[0] * 0.9 / 2  # backoff grows (jittered)


def test_gives_up_after_max_attempts():
    calls = []

    def always():
        calls.append(1)
        raise TransientError("503")

    with pytest.raises(TransientError):
        retry_call(always, attempts=3, base_delay=0, sleep=lambda s: None)
    assert len(calls) == 3


def test_permanent_errors_are_not_retried():
    calls = []

    def bad():
        calls.append(1)
        raise PermanentError("400")

    with pytest.raises(PermanentError):
        retry_call(bad, attempts=5, base_delay=0, sleep=lambda s: None)
    assert len(calls) == 1


def test_backoff_is_exponential_and_capped():
    assert [backoff_delay(a, 1, cap=5, jitter=False) for a in (1, 2, 3, 4)] == [1, 2, 4, 5]
