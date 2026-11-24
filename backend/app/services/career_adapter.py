CAREER_INTERESTS = {"Tech", "Finance", "Business", "Design", "Healthcare"}


def profile_to_features(profile) -> dict:
    """Map stored model-feature JSON, applying documented defaults for absent fields."""
    data = profile.profile_data or {}
    interest = str(data.get("Career_Interests", "Other")).strip()
    if interest not in CAREER_INTERESTS:
        interest = "Other"

    return {
        "Age": int(data.get("Age", 18)),
        "Gender": str(data.get("Gender") or "Other"),
        "Field_of_Study": str(data.get("Field_of_Study") or "Other"),
        "Year_of_Study": int(data.get("Year_of_Study", 1)),
        "University_Location": str(data.get("University_Location") or "Region A"),
        "GPA": float(data.get("GPA", 0.0)),
        "Relevant_Coursework": int(bool(data.get("Relevant_Coursework", 0))),
        "Prior_Employment": int(bool(data.get("Prior_Employment", 0))),
        "Employment_Type": str(data.get("Employment_Type") or "None"),
        "Entrepreneurial_Experience": int(bool(data.get("Entrepreneurial_Experience", 0))),
        "Startup_Participation": int(bool(data.get("Startup_Participation", 0))),
        "Career_Interests": interest,
        "Entrepreneurial_Aspirations": str(data.get("Entrepreneurial_Aspirations") or "Low"),
    }