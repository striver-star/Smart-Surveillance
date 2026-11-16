import cv2
import numpy as np

from worker.attributes import COLOURS, colour_names, describe, dominant, regions
from worker.detector import Detection


def bgr(name):
    return {"red": (30, 30, 210), "blue": (200, 90, 30), "green": (40, 170, 40), "yellow": (30, 220, 230), "white": (245, 245, 245),
            "black": (15, 15, 15), "grey": (128, 128, 128), "orange": (20, 120, 240), "purple": (150, 40, 120), "brown": (30, 60, 110),
            "pink": (190, 160, 245)}[name]


def test_named_colours():
    for name in ("red", "blue", "green", "yellow", "white", "black", "grey", "orange", "purple", "brown", "pink"):
        img = np.full((10, 10, 3), bgr(name), np.uint8)
        got = COLOURS[int(colour_names(cv2.cvtColor(img, cv2.COLOR_BGR2HSV))[0, 0])]
        assert got == name, (name, got)


def test_dominant_and_second_colour():
    img = np.full((40, 40, 3), bgr("blue"), np.uint8)
    assert dominant(img) == ["blue"]
    img[:, 25:] = bgr("white")                                    # 37 % white stripe
    assert dominant(img) == ["blue", "white"]
    assert dominant(np.zeros((2, 2, 3), np.uint8)) == []


def test_person_regions_and_drawn_outline_ignored():
    img = np.full((400, 300, 3), bgr("grey"), np.uint8)
    img[100:220, 100:200] = bgr("red")                            # top
    img[230:330, 100:200] = bgr("blue")                           # trousers
    cv2.rectangle(img, (100, 60), (200, 340), (0, 0, 255), 3)     # the red box the server AI draws
    people = describe(img, [Detection("human", 0.9, (100, 60, 200, 340))])
    assert people[0]["upper"][0] == "red" and people[0]["lower"][0] == "blue"
    assert "body" in regions((0, 0, 100, 60), "vehicle", (400, 300))
    assert describe(img, [Detection("human", 0.9, (10, 10, 20, 30))]) == []      # too small to judge
