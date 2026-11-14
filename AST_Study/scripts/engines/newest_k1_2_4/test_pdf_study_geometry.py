import copy
import unittest
from pdf_study_geometry import shared_endpoints


def edge(y=40, end=(90,20), curved=True):
    return {'stroke':True,'fill':False,'pts':[(10,80),(50,y),end],
        'path':[('m',(10,80)),('c' if curved else 'l',end)],
        'x0':10,'x1':90,'top':min(y,20),'bottom':max(80,y)}


class GeometryTests(unittest.TestCase):
    def test_distinct_curved_paths_share_endpoints_in_either_direction(self):
        paths=[edge(10),edge(50),edge(90)]
        paths[2]['pts'].reverse()
        self.assertEqual(len(shared_endpoints(paths,100,100)[0]),3)

    def test_successive_segments_and_duplicate_strokes_are_not_alternatives(self):
        self.assertEqual(shared_endpoints([edge(10,(30,50)),edge(50,(60,50)),edge(90)],100,100),[])
        one=edge();self.assertEqual(shared_endpoints([one,copy.deepcopy(one),copy.deepcopy(one)],100,100),[])
        self.assertEqual(shared_endpoints([edge(i,curved=False)for i in [10,50,90]],100,100),[])

    def test_closed_filled_shapes_do_not_create_paths(self):
        paths=[edge(i)for i in [10,50,90]]
        for path in paths:path['path'].append(('h',))
        self.assertEqual(shared_endpoints(paths,100,100),[])
        for path in paths:path['path'].pop();path['fill']=True
        self.assertEqual(shared_endpoints(paths,100,100),[])

if __name__=='__main__':unittest.main()
