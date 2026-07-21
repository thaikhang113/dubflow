import unittest
from series_compilation import normalize_state,select,pack
class TestCompilation(unittest.TestCase):
 def setUp(self): self.raw={'version':1,'series':[{'series_id':'s','episodes':[{'episode_number':'2','duration':'01:00','status':'ready'},{'number':1,'duration':5400,'status':'processed'},{'episode_number':3,'duration':'5401','status':'ready'}]}]}
 def test_migration_selectors(self):
  s=normalize_state(self.raw); self.assertEqual(s['version'],2); self.assertEqual([e['episode_number'] for e in select(s,'range:1-2')],[1,2]); self.assertEqual([e['episode_number'] for e in select(s,'list:3')],[3]); self.assertEqual([e['episode_number'] for e in select(s,'latest')],[3]); self.assertEqual([e['episode_number'] for e in select(s,'latest:2')],[2,3]); self.assertEqual([e['episode_number'] for e in select(s,'unprocessed')],[2,3])
  with self.assertRaisesRegex(ValueError,'positive integer'): select(s,'latest:0')
 def test_unprocessed_excludes_outputs_and_localization(self):
  state={'series':[{'episodes':[{'episode_number':1,'final_video_path':'declared.mp4'},{'episode_number':2,'final_video_vi':'declared.mp4'},{'episode_number':3,'localization':{'status':'done'}},{'episode_number':4,'status':'ready'}]}]}
  self.assertEqual([e['episode_number'] for e in select(state,'unprocessed')],[4])
 def test_boundaries_large(self):
  r=pack([{'episode_number':1,'duration_seconds':5380},{'episode_number':2,'duration_seconds':10},{'episode_number':3,'duration_seconds':5401}],5,5); self.assertEqual([m['episode_numbers'] for m in r['manifests']],[[1,2],[3]]); self.assertTrue(r['warnings'])
 def test_idempotent(self): self.assertEqual(pack(select(self.raw),5,5),pack(select(self.raw),5,5))
if __name__=='__main__':unittest.main()
