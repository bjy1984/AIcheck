"""包围盒几何：拿数字直接验。

这批函数原先埋在三万行的 routes.py 里，没有任何单测。它们算错不会报错——
IoU 偏一点，「命中率」这类指标就悄悄不准，而指标不准的方向恰恰是没人会怀疑的。

搬出来单独成模块的意义就在这里：能测了才谈得上健康。
"""

from __future__ import annotations

from libs.ocr_expected_geometry import (
    expected_bbox_area,
    expected_bbox_extents,
    expected_bbox_intersection_area,
    expected_bbox_iou,
    expected_bbox_overlap_ratio,
    expected_float,
    expected_full_page_bbox,
)

# 两个 10×10 的框，右下角与左上角重叠 5×5
A = [0, 0, 10, 10]
B = [5, 5, 15, 15]


def test_面积():
    assert expected_bbox_area(A) == 100
    assert expected_bbox_area([0, 0, 0, 0]) == 0


def test_交集与并比():
    assert expected_bbox_intersection_area(A, B) == 25
    # IoU = 交 / (并) = 25 / (100 + 100 - 25) = 25/175
    assert abs(expected_bbox_iou(A, B) - 25 / 175) < 1e-9


def test_完全不相交时为零():
    far = [100, 100, 110, 110]
    assert expected_bbox_intersection_area(A, far) == 0
    assert expected_bbox_iou(A, far) == 0


def test_完全重合时_iou_为一():
    assert abs(expected_bbox_iou(A, list(A)) - 1.0) < 1e-9


def test_重叠比按较小框算而不是并集():
    """overlap_ratio 与 IoU 是两个口径，混用会让「基本重合」的判断偏松或偏紧。"""
    small = [0, 0, 5, 5]
    big = [0, 0, 10, 10]
    # 小框完全落在大框里：重叠比应为 1，而 IoU 只有 25/100
    assert abs(expected_bbox_overlap_ratio(small, big) - 1.0) < 1e-9
    assert abs(expected_bbox_iou(small, big) - 0.25) < 1e-9


def test_坐标顺序颠倒要归一():
    assert expected_bbox_extents([3, 4, 1, 2]) == [1, 2, 3, 4]


def test_退化的框返回_none_而不是零面积框():
    """x0 == x1 的「框」不是一个框。返回 [3,4,3,9] 这种零宽框会让下游
    算出 IoU=0 并当成「没命中」，而真实情况是「这个框本身就是坏的」。"""
    assert expected_bbox_extents([3, 4, 3, 9]) is None
    assert expected_bbox_extents([3, 4, 8, 4]) is None
    assert expected_bbox_extents([]) is None
    assert expected_bbox_extents("不是列表") is None


def test_多边形坐标也能取到外接框():
    """OCR 引擎有时给四点多边形而不是矩形。"""
    assert expected_bbox_extents([[1, 2], [9, 2], [9, 7], [1, 7]]) == [1, 2, 9, 7]
    assert expected_bbox_extents([1, 2, 9, 2, 9, 7, 1, 7]) == [1, 2, 9, 7]


def test_expected_float_的默认值是_0_并且这是个坑():
    """默认 0.0 会让「没有这个值」和「值就是 0」无法区分。

    函数把 default 开成了参数，所以调用方可以选；这条测试把默认行为钉住，
    也把这个风险写在明处——置信度取不到时默认 0.0，恰好等于「最低置信度」，
    方向上是保守的；但换个场景（面积、页码）默认 0 就可能被当成有效值。
    """
    assert expected_float("1.5") == 1.5
    assert expected_float(None) == 0.0
    assert expected_float("不是数字") == 0.0
    assert expected_float(None, default=-1.0) == -1.0


def test_整页包围盒从_ocr_结果里取页面尺寸():
    assert expected_full_page_bbox({"pages": [{"width": 1000, "height": 800}]}) == [0, 0, 1000, 800]
    # 别名字段也要认——不同引擎叫法不一
    assert expected_full_page_bbox({"pages": [{"imageWidth": 640, "imageHeight": 480}]}) == [0, 0, 640, 480]
    # 尺寸缺失时返回 None，而不是 [0,0,0,0] 那种「看起来是个框」的东西
    assert expected_full_page_bbox({"pages": [{}]}) is None
    assert expected_full_page_bbox({}) is None
