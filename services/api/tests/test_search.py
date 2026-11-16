from app.search import matches, slot

P = {"class": "human", "upper": ["red", "white"], "lower": ["blue"]}
V = {"class": "vehicle", "body": ["white"]}


def test_person_colours():
    assert matches(P, "person", ["red"], [], []) and matches(P, "person", ["white"], ["blue"], [])
    assert matches(P, "person", [], [], [])
    assert not matches(P, "person", ["green"], [], []) and not matches(P, "person", ["red"], ["black"], [])
    assert not matches(V, "person", [], [], [])


def test_vehicle_and_any():
    assert matches(V, "vehicle", [], [], ["white", "grey"]) and not matches(V, "vehicle", [], [], ["black"])
    assert matches(V, "any", [], [], []) and matches(P, "any", [], [], [])
    assert not matches({"class": "dog"}, "any", [], [], [])


def test_same_spot_folds():
    a = {"class": "vehicle", "box": [651, 43, 725, 100]}
    b = {"class": "vehicle", "box": [650, 44, 726, 101]}
    c = {"class": "vehicle", "box": [100, 300, 260, 420]}
    assert slot("cam", a) == slot("cam", b) != slot("cam", c)
    assert slot("cam", a) != slot("other", a)
    red = {"class": "human", "box": [10, 10, 50, 120], "upper": ["red"]}
    blue = {"class": "human", "box": [10, 10, 50, 120], "upper": ["blue"]}
    assert slot("cam", red) != slot("cam", blue)                              # two people at the same post stay apart
