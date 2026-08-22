import pytest

from app.config import Settings


def test_production_rejects_documented_placeholder_peppers():
    config = Settings(
        app_env="production",
        jwt_secret="a-production-secret-that-is-long-enough",
        auth_sms_provider="tencent",
        auth_otp_pepper="replace-with-random-secret",
        auth_refresh_token_pepper="replace-with-different-random-secret",
        auth_invite_pepper="replace-with-third-random-secret",
    )

    with pytest.raises(RuntimeError, match="AUTH_OTP_PEPPER"):
        config.validate_production()
