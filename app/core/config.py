"""
Central configuration, including the CONFIGURABLE hybrid matching weights
required by the SIH 26099 spec ("weights must be configurable rather than
hardcoded"). These can be overridden via environment variables or a .env
file without touching any matching code.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./sih26099.db"

    # --- Hybrid scoring weights (Phase 5) ---
    # Must sum to 1.0 for the final_confidence to stay in [0, 1]; validated at startup.
    WEIGHT_LEXICAL: float = 0.25
    WEIGHT_SEMANTIC: float = 0.35
    WEIGHT_TECHNICAL: float = 0.40

    # --- Match classification thresholds (Phase 6) ---
    THRESHOLD_EXACT_DUPLICATE: float = 0.97
    THRESHOLD_NEAR_DUPLICATE: float = 0.90
    THRESHOLD_FUNCTIONALLY_EQUIVALENT: float = 0.75
    THRESHOLD_POSSIBLE_MATCH: float = 0.55
    # below THRESHOLD_POSSIBLE_MATCH => DISTINCT_MATERIAL

    # --- Attribute similarity tolerances ---
    SIZE_TOLERANCE_MM: float = 0.5

    # --- Matching engine behavior ---
    MIN_CONFIDENCE_TO_STORE: float = 0.50  # don't persist near-zero noise matches
    CROSS_CPSE_ONLY: bool = True           # only match materials from different CPSEs

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()

# Fail fast if weights are misconfigured -- silent wrong-weight bugs are worse
# than a startup crash for a scoring system whose transparency is a hard requirement.
_weight_sum = settings.WEIGHT_LEXICAL + settings.WEIGHT_SEMANTIC + settings.WEIGHT_TECHNICAL
if abs(_weight_sum - 1.0) > 1e-6:
    raise ValueError(
        f"WEIGHT_LEXICAL + WEIGHT_SEMANTIC + WEIGHT_TECHNICAL must sum to 1.0, "
        f"got {_weight_sum}. Check your .env or environment variables."
    )
