from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .farm_memory import LanguageCode


class AnswerType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    CROP_NAME = "crop_name"
    FREE_TEXT = "free_text"


class AllowedChoice(BaseModel):
    value: str
    labels: dict[str, str] = Field(
        ..., description="Human-readable labels keyed by 'en' and 'ms'."
    )


class QuestionItem(BaseModel):
    """Approved plain-language interview question mapped to a FarmMemory field."""

    question_id: str
    target_field: str
    prompts: dict[str, str]
    confirmation_templates: dict[str, str]
    answer_type: AnswerType
    allowed_values: list[AllowedChoice] = Field(default_factory=list)
    ask_when: list[str] = Field(default_factory=list)
    priority: int = Field(1, ge=1)


class QuestionLibrary(BaseModel):
    version: str
    questions: list[QuestionItem]


class OpenQuestionType(str, Enum):
    INTERVIEW_ANSWER = "interview_answer"
    SPONTANEOUS_EVENT = "spontaneous_event"
    RESULT_EXPLANATION = "result_explanation"
    WHAT_IF_SCENARIO = "what_if_scenario"
    GENERAL_FARMING = "general_farming"
    MISSING_FACTS = "missing_facts"
    HIGH_STAKES_EXPERT_REFERRAL = "high_stakes_expert_referral"
    OUT_OF_SCOPE = "out_of_scope"


class PendingConfirmation(BaseModel):
    """Fact extracted by the LLM that must be confirmed by the farmer before saving."""

    confirmation_id: str
    target_field: str
    proposed_value: Any
    human_label: str
    confirmation_prompt: str


class VoiceChatRequest(BaseModel):
    farm_id: str
    session_id: str
    language: LanguageCode = LanguageCode.MS
    text: str
    current_question_id: Optional[str] = None


class VoiceTurnResponse(BaseModel):
    """Response returned to the Stitch JS frontend for both audio and text turns."""

    session_id: str
    language: LanguageCode
    transcript: str
    question_type: OpenQuestionType
    assistant_text: str
    tts_audio_base64: Optional[str] = None
    pending_confirmation: Optional[PendingConfirmation] = None
    next_question_id: Optional[str] = None
    answer_basis: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)


class VoiceConfirmRequest(BaseModel):
    farm_id: str
    session_id: str
    confirmation_id: str
    accepted: bool
    language: LanguageCode = LanguageCode.MS
    target_field: Optional[str] = None
    proposed_value: Optional[Any] = None
    human_label: Optional[str] = None
    confirmation_prompt: Optional[str] = None
