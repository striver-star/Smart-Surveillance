from app.recognition import normalise_plate, suggest_threshold


def test_plate_normalising():
    assert normalise_plate("kja-123 ab") == "KJA123AB" and normalise_plate("") == ""


def test_threshold_suggestion_from_verdicts():
    confirmed = [0.62, 0.58, 0.71, 0.55, 0.66, 0.60, 0.49, 0.64, 0.68, 0.57, 0.61, 0.59, 0.70, 0.63, 0.52, 0.67]
    rejected = [0.41, 0.43, 0.44, 0.42]
    assert suggest_threshold(confirmed[:5], rejected, 0.40) is None               # too few verdicts yet
    assert suggest_threshold(confirmed, rejected, 0.40) == 0.45                   # just above the highest rejected
    assert suggest_threshold(confirmed, rejected + [0.60], 0.40) is None          # would lose too many true matches
    assert suggest_threshold(confirmed, [], 0.40) is None                         # nothing rejected: keep it
    assert suggest_threshold(confirmed, rejected, 0.50) is None                   # already stricter
