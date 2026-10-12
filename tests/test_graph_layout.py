import math
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import bootstrap
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from layout_fixtures import CASES, make_report
from group_relations.graph_layout import curve_point, positions_for, route_link
from group_relations.render import graph_svg, image_html, overview


class LayoutTests(unittest.TestCase):
    def test_high_degree_member_is_centered(self):
        graph = overview(make_report(12, 'hub', 11))
        positions, _ = positions_for(graph['nodes'], graph['roles'])
        self.assertLess(math.hypot(positions['demo-0'][0]-500, positions['demo-0'][1]-300), 50)

    def test_fixture_labels_do_not_hide_avatars_or_names(self):
        ns = {'s':'http://www.w3.org/2000/svg'}
        def rect(element, offset=(0,0)):
            return (float(element.get('x'))+offset[0], float(element.get('y'))+offset[1],
                    float(element.get('width')), float(element.get('height')))
        def overlaps(a,b):
            return min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0]) > .1 and min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]) > .1
        for key, _, count, kind, role_count in CASES:
            with self.subTest(case=key):
                tree = ET.fromstring(graph_svg(make_report(count, kind, role_count)))
                labels = [rect(r) for r in tree.findall('.//s:rect[@class="relation-label"]', ns)]
                for group in tree.findall('.//s:g[@class="node"]', ns):
                    x,y = map(float, re.findall(r'-?[\d.]+', group.get('transform')))
                    caption = rect(group.find('s:rect[@class="member-name"]', ns), (x,y))
                    for label in labels:
                        self.assertFalse(overlaps(label, caption), (key, label, caption))
                        near_x = max(label[0], min(x, label[0]+label[2]))
                        near_y = max(label[1], min(y, label[1]+label[3]))
                        self.assertGreater(math.hypot(near_x-x, near_y-y), 30)
                for i, label in enumerate(labels):
                    for other in labels[i+1:]:
                        self.assertFalse(overlaps(label, other), (key, label, other))

    def test_avatar_name_boxes_stay_separate_and_inside_canvas(self):
        for key, _, count, kind, role_count in CASES:
            with self.subTest(case=key):
                graph = overview(make_report(count, kind, role_count))
                points, height = positions_for(graph['nodes'], graph['edges']+graph['roles'])
                self.assertEqual((points, height), positions_for(graph['nodes'], graph['edges']+graph['roles']))
                values = list(points.values())
                for i, (x,y) in enumerate(values):
                    self.assertTrue(98 <= x <= 902 and 38 <= y <= height-98)
                    for a,b in values[i+1:]:
                        self.assertTrue(abs(x-a) >= 207 or abs(y-b) >= 141)

    def test_curves_end_at_members_and_labels_stay_on_curve(self):
        for key, _, count, kind, role_count in CASES:
            with self.subTest(case=key):
                graph = overview(make_report(count, kind, role_count))
                points, height = positions_for(graph['nodes'], graph['edges']+graph['roles'])
                labels = []
                for role in graph['roles']:
                    start, end = points[role['source']], points[role['target']]
                    width = len(role['label'])*18/2+10
                    route = route_link(start, end, points, height, half_width=width, labels=labels)
                    self.assertEqual(curve_point(start, route['control'], end, 0), start)
                    self.assertEqual(curve_point(start, route['control'], end, 1), end)
                    self.assertEqual(route['label'], curve_point(start, route['control'], end, route['t']))
                    # Bounded gentle bow: at most 28px deviation at the midpoint.
                    middle = curve_point(start, route['control'], end, .5)
                    self.assertLessEqual(math.hypot(middle[0]-(start[0]+end[0])/2, middle[1]-(start[1]+end[1])/2), 28.001)
                    self.assertTrue(all(math.isfinite(v) for point in (start, end, route['control'], route['label']) for v in point))
                    x,y = route['label']
                    self.assertTrue(width+8 <= x <= 992-width and 18 <= y <= height-18)
                    labels.append((x,y,width))

    def test_dense_sample_preserves_all_cards_and_real_labels(self):
        report = make_report(54, 'dense', 20)
        svg = graph_svg(report)
        self.assertNotIn('<polyline', svg)
        self.assertNotRegex(svg, r'>R\d+</text>')
        self.assertIn('>欢喜冤家</text>', svg)
        self.assertEqual(image_html(report).count('<article class="role">'), 20)
        self.assertEqual(report['meta']['members'], 54)


if __name__ == '__main__':
    unittest.main()
