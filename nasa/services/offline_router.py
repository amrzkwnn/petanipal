from typing import Any, Dict, Optional

from schemas import FarmMemory, LanguageCode, OpenQuestionType, QuestionItem
from services.library_store import LibraryStore
from services.openai_voice import LLMExtractionResult


def route_offline(
    transcript: str,
    language: LanguageCode,
    farm: FarmMemory,
    current_question: Optional[QuestionItem],
    libraries: LibraryStore,
    comparison_context: Optional[Dict[str, Any]] = None,
) -> LLMExtractionResult:
    text = (transcript or "").strip()
    lower = text.lower()
    is_ms = language == LanguageCode.MS

    # 0. Strict off-topic guardrail (unless clear farming/plot terms are present)
    farming_terms = [
        "crop", "tanam", "pokok", "kebun", "petak", "ladang", "plot", "soil", "tanah",
        "water", "air", "rain", "hujan", "flood", "banjir", "bertakung", "pump", "pam",
        "pest", "ulat", "serangga", "disease", "penyakit", "kulat", "weed", "rumput",
        "rotation", "giliran", "season", "musim", "harvest", "tuai", "ph", "nasa",
        "climate", "cuaca", "panas", "kemarau", "kering", "basah", "jagung", "kacang",
        "cili", "chilli", "keledek", "padi", "betik", "nanas", "skip", "tak pasti",
    ]
    off_topic_terms = [
        "bitcoin", "crypto", "saham", "stock market", "python", "javascript", "coding",
        "write code", "html", "recipe", "resipi", "masak", "football", "bola sepak",
        "movie", "filem", "netflix", "politics", "politik", "election", "pilihan raya",
        "homework", "kerja sekolah", "math", "matematik", "tell me a joke", "lawak",
        "horoscope", "lottery", "4d", "toto", "ignore previous", "ignore your rules",
        "pretend you are",
    ]
    if any(t in lower for t in off_topic_terms) and not any(f in lower for f in farming_terms):
        reply = (
            "Maaf, saya hanya boleh membantu tentang kebun anda, giliran tanaman, keadaan tanah dan air, serta data iklim NASA POWER. Ada apa-apa tentang petak anda yang ingin disemak?"
            if is_ms
            else "Sorry, I can only help with your farm plot, crop rotation, soil and water conditions, and NASA POWER climate insights. What would you like to check for your plot?"
        )
        return LLMExtractionResult(
            question_type=OpenQuestionType.OUT_OF_SCOPE,
            assistant_text=reply,
            needs_confirmation=False,
            answer_basis=["Scope Policy: Farm & Crop Rotation Only"],
            missing_info=[],
        )

    # 1. High-stakes chemical / pesticide / disease diagnosis safety referral
    high_stakes_terms = [
        "racun",
        "ml/l",
        "dos ",
        "dosage",
        "pesticide",
        "fungicide",
        "insecticide",
        "chemical",
        "sembur apa",
        "ubat apa",
    ]
    if any(t in lower for t in high_stakes_terms):
        reply = (
            "Untuk pemilihan racun makhluk perosak atau kadar bancuhan (ml/L), sila rujuk pegawai pengembangan Jabatan Pertanian (DOA) tempatan dan patuhi label rasmi produk. Saya boleh bantu rekodkan pemerhatian perosak ini dalam memori kebun anda."
            if is_ms
            else "For specific pesticide selection or chemical dosage rates, please consult a local Department of Agriculture (DOA) extension officer and follow the registered product label. I can log this pest observation in your farm memory."
        )
        return LLMExtractionResult(
            question_type=OpenQuestionType.HIGH_STAKES_EXPERT_REFERRAL,
            assistant_text=reply,
            needs_confirmation=False,
            answer_basis=["Safety Policy: High-Stakes Chemical & Diagnosis Referral", "DOA Malaysia Extension Guideline"],
            missing_info=["On-site pest/disease identification by agricultural officer"],
        )

    # 2. What-if scenario
    if any(
        w in lower
        for w in ["what if", "kalau musim depan", "drier", "wetter", "lebih kering", "lebih basah", "kemarau"]
    ):
        opts = (comparison_context or {}).get("options", [])
        top_names = ", ".join(o.get("name_ms" if is_ms else "name_en", "") for o in opts[:2]) or (
            "kacang tanah dan jagung" if is_ms else "groundnut and sweet corn"
        )
        reply = (
            f"Jika musim depan lebih kering atau hujan berubah, tanaman dengan keperluan air sederhana seperti {top_names} mempunyai risiko tekanan air yang berbeza; pastikan sungkupan organik dan sumber air simpanan. Ini adalah senario sejarah, bukan ramalan cuaca."
            if is_ms
            else f"If next season shifts drier or wetter, options like {top_names} trade off water demand against drainage risk; mulching and backup water access reduce establishment stress. This is a historical scenario, not a weather forecast."
        )
        return LLMExtractionResult(
            question_type=OpenQuestionType.WHAT_IF_SCENARIO,
            assistant_text=reply,
            needs_confirmation=False,
            answer_basis=[
                "NASA POWER 30-day agroclimatology scenario",
                "Reviewed Crop Library",
                "Farm Memory",
            ],
            missing_info=["Confirmed backup irrigation capacity"],
        )

    # 3. Result explanation ("why" / "kenapa")
    if any(w in lower for w in ["kenapa", "mengapa", "why", "explain", "jelaskan", "bandingkan"]):
        matched = libraries.match_crop_name(lower)
        if matched is None:
            for c in libraries.list_crops():
                for n in c.names.get("en", []) + c.names.get("ms", []):
                    if n.lower() in lower:
                        matched = c
                        break
                if matched:
                    break
        crop_label = (
            matched.names["ms" if is_ms else "en"][0]
            if matched
            else ("kacang tanah" if is_ms else "groundnut")
        )
        family_label = matched.family if matched else "Fabaceae"
        reply = (
            f"Pilihan {crop_label} ({family_label}) dibandingkan berdasarkan keluarga botani berbeza untuk memutuskan kitaran perosak, keperluan air tanaman, serta rekod saliran petak anda."
            if is_ms
            else f"{crop_label.title()} ({family_label}) is compared based on botanical family rotation to break pest cycles, crop water requirement, and your recorded plot drainage."
        )
        return LLMExtractionResult(
            question_type=OpenQuestionType.RESULT_EXPLANATION,
            assistant_text=reply,
            needs_confirmation=False,
            answer_basis=[
                f"Reviewed Crop Library: {matched.crop_id if matched else 'kacang_tanah'}",
                "NASA POWER Climate Summary",
                "Farm Memory",
            ],
            missing_info=[],
        )

    # 4. Spontaneous field observation (unless specifically answering the field_problems interview question with a short choice)
    spontaneous_triggers = [
        "air bertakung 3 hari",
        "bahagian rendah",
        "pam rosak",
        "broken pump",
        "banyak ulat",
        "thrips",
        "anthracnose",
        "tuai awal",
        "flooded yesterday",
        "water stood",
    ]
    if any(t in lower for t in spontaneous_triggers) and (
        current_question is None or current_question.question_id != "field_problems"
    ):
        ev_type = (
            "flooding"
            if any(k in lower for k in ["bertakung", "banjir", "flood", "water stood"])
            else ("equipment" if "pam" in lower or "pump" in lower else "pest")
        )
        zone = "bahagian rendah" if "rendah" in lower else ("lower area" if "lower" in lower else "general")
        prompt = (
            f"Saya dengar pemerhatian kebun ({ev_type}): '{text}'. Nak saya simpan dalam rekod kebun? Betul ke?"
            if is_ms
            else f"I heard a field observation ({ev_type}): '{text}'. Should I save this to your farm memory?"
        )
        return LLMExtractionResult(
            question_type=OpenQuestionType.SPONTANEOUS_EVENT,
            assistant_text=prompt,
            extracted_target_field="field_observations",
            extracted_value=text,
            human_label=text,
            observation_zone=zone,
            observation_event_type=ev_type,
            needs_confirmation=True,
            confirmation_prompt=prompt,
            answer_basis=["Farm Memory"],
            missing_info=[],
        )

    # 5. Interview answer for current_question
    if current_question is not None:
        qf = current_question.target_field
        qid = current_question.question_id

        if any(
            u in lower
            for u in ["skip", "tak tahu", "tak pasti", "not sure", "i don't know", "dont know", "entah"]
        ):
            label = "Tak pasti" if is_ms else "Not sure"
            tmpl = current_question.confirmation_templates.get(
                language.value, current_question.confirmation_templates["en"]
            )
            prompt = tmpl.format(label=label)
            return LLMExtractionResult(
                question_type=OpenQuestionType.INTERVIEW_ANSWER,
                assistant_text=prompt,
                extracted_target_field=qf,
                extracted_value="unknown",
                human_label=label,
                needs_confirmation=True,
                confirmation_prompt=prompt,
                answer_basis=["Farm Memory"],
                missing_info=[qf],
            )

        if qf == "crop_history":
            matched = libraries.match_crop_name(lower)
            if matched is None:
                for c in libraries.list_crops():
                    for n in c.names.get("en", []) + c.names.get("ms", []):
                        if n.lower() in lower:
                            matched = c
                            break
                    if matched:
                        break
            crop_id = matched.crop_id if matched else None
            label = (
                matched.names["ms" if is_ms else "en"][0]
                if matched
                else text
            )
            tmpl = current_question.confirmation_templates.get(
                language.value, current_question.confirmation_templates["en"]
            )
            prompt = tmpl.format(label=label)
            return LLMExtractionResult(
                question_type=OpenQuestionType.INTERVIEW_ANSWER,
                assistant_text=prompt,
                extracted_target_field="crop_history",
                extracted_value=crop_id or text,
                matched_crop_id=crop_id,
                human_label=label,
                needs_confirmation=True,
                confirmation_prompt=prompt,
                answer_basis=["Farm Memory", "Reviewed Crop Library"],
                missing_info=[],
            )

        if qid == "field_problems" or qf == "field_observations":
            val = "general"
            label = text
            ev_type = "general"
            if any(k in lower for k in ["penyakit", "disease", "kulat", "fungus", "antraknos"]):
                val = "disease"
                ev_type = "disease"
                label = "Penyakit pokok" if is_ms else "Plant disease"
            elif any(k in lower for k in ["serangga", "ulat", "insect", "bug", "pest", "thrips"]):
                val = "insects"
                ev_type = "pest"
                label = "Serangga / ulat" if is_ms else "Bugs / insects"
            elif any(k in lower for k in ["rumput", "lalang", "weed"]):
                val = "weeds"
                ev_type = "weeds"
                label = "Rumput / lalang" if is_ms else "Weeds"
            elif any(k in lower for k in ["terlebih air", "too much water", "banjir", "bertakung"]):
                val = "too_much_water"
                ev_type = "flooding"
                label = "Terlebih air" if is_ms else "Too much water"
            elif any(k in lower for k in ["tak cukup air", "not enough water", "kering"]):
                val = "too_little_water"
                ev_type = "irrigation"
                label = "Tak cukup air" if is_ms else "Not enough water"

            tmpl = current_question.confirmation_templates.get(
                language.value, current_question.confirmation_templates["en"]
            )
            prompt = tmpl.format(label=label)
            return LLMExtractionResult(
                question_type=OpenQuestionType.INTERVIEW_ANSWER,
                assistant_text=prompt,
                extracted_target_field="field_observations",
                extracted_value=val,
                human_label=label,
                observation_zone="general",
                observation_event_type=ev_type,
                needs_confirmation=True,
                confirmation_prompt=prompt,
                answer_basis=["Farm Memory"],
                missing_info=[],
            )

        for choice in current_question.allowed_values:
            c_val = choice.value.lower()
            lbl_en = choice.labels.get("en", "").lower()
            lbl_ms = choice.labels.get("ms", "").lower()
            if c_val in lower or (lbl_en and lbl_en in lower) or (lbl_ms and lbl_ms in lower):
                label = choice.labels.get(language.value, choice.labels.get("en", choice.value))
                tmpl = current_question.confirmation_templates.get(
                    language.value, current_question.confirmation_templates["en"]
                )
                prompt = tmpl.format(label=label)
                return LLMExtractionResult(
                    question_type=OpenQuestionType.INTERVIEW_ANSWER,
                    assistant_text=prompt,
                    extracted_target_field=qf,
                    extracted_value=choice.value,
                    human_label=label,
                    needs_confirmation=True,
                    confirmation_prompt=prompt,
                    answer_basis=["Farm Memory"],
                    missing_info=[],
                )

        # Heuristic keyword matching for single_choice questions
        if qf == "irrigation_availability":
            val = "always" if any(k in lower for k in ["sentiasa", "always", "ada pam", "ada air"]) else (
                "no" if any(k in lower for k in ["tak ada", "tiada", "no water", "hujan je"]) else "sometimes"
            )
        elif qf == "priorities":
            val = "water" if "air" in lower or "water" in lower else (
                "soil_health" if "tanah" in lower or "soil" in lower else (
                    "income" if "untung" in lower or "earn" in lower else "risk_reduction"
                )
            )
        elif qf == "soil.flooded_last_season":
            val = "yes" if any(k in lower for k in ["ya", "pernah", "yes", "banjir", "flooded"]) else "no"
        elif qf == "soil.waterlogging_duration":
            val = "over_2_days" if any(k in lower for k in ["lebih", "3 hari", "more than", "over"]) else (
                "1_to_2_days" if any(k in lower for k in ["sehari", "dua hari", "1", "2"]) else "same_day"
            )
        elif qf == "soil.texture_feel":
            val = "sticky" if any(k in lower for k in ["melekit", "liat", "sticky", "clay"]) else (
                "sandy" if any(k in lower for k in ["pasir", "sandy"]) else "in_between"
            )
        elif qf == "soil.soil_test_status":
            val = "yes_known" if "keputusan" in lower or "know" in lower else (
                "yes_unknown_result" if "tak ingat" in lower else "no_test"
            )
        elif qf == "soil.trouble_spot":
            val = "low_flooding_area" if any(k in lower for k in ["rendah", "air", "low", "flood"]) else (
                "dry_area" if "kering" in lower or "dry" in lower else (
                    "slope" if "cerun" in lower or "bukit" in lower or "slope" in lower else "no_problem"
                )
            )
        else:
            val = "yes" if any(k in lower for k in ["cukup", "yes", "ada"]) else "maybe"

        label = val
        for choice in current_question.allowed_values:
            if choice.value == val:
                label = choice.labels.get(language.value, choice.labels.get("en", val))
                break
        tmpl = current_question.confirmation_templates.get(
            language.value, current_question.confirmation_templates["en"]
        )
        prompt = tmpl.format(label=label)
        return LLMExtractionResult(
            question_type=OpenQuestionType.INTERVIEW_ANSWER,
            assistant_text=prompt,
            extracted_target_field=qf,
            extracted_value=val,
            human_label=label,
            needs_confirmation=True,
            confirmation_prompt=prompt,
            answer_basis=["Farm Memory"],
            missing_info=[],
        )

    if any(f in lower for f in farming_terms):
        fallback_reply = (
            "Saya sedia membantu membandingkan pilihan giliran tanaman dan merekodkan pemerhatian kebun anda."
            if is_ms
            else "I can help compare crop rotation options and log observations for your plot."
        )
        return LLMExtractionResult(
            question_type=OpenQuestionType.GENERAL_FARMING,
            assistant_text=fallback_reply,
            needs_confirmation=False,
            answer_basis=["Farm Memory", "Reviewed Crop Library"],
            missing_info=[],
        )

    redirect_reply = (
        "Maaf, saya hanya fokus pada penanaman, giliran tanaman, dan keadaan kebun anda. Boleh kongsikan tentang petak atau tanaman anda?"
        if is_ms
        else "I stay focused on your farm plot, crop rotation, and NASA climate trade-offs. Would you like to check a crop or field condition?"
    )
    return LLMExtractionResult(
        question_type=OpenQuestionType.OUT_OF_SCOPE,
        assistant_text=redirect_reply,
        needs_confirmation=False,
        answer_basis=["Scope Policy: Farm & Crop Rotation Only"],
        missing_info=[],
    )
