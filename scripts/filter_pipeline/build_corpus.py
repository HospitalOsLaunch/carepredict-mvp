"""Independent trajectories can be generated concurrently within stage 3."""
from concurrent.futures import ProcessPoolExecutor
from common import PROTO
from longitudinal import run

if __name__=='__main__':
 jobs=[(part,i) for part in (PROTO['jepa_train'],PROTO['jepa_test']) for i in range(PROTO['jepa_structures_per_partition'])]
 with ProcessPoolExecutor(max_workers=6) as pool:
  futures=[pool.submit(run,part,i) for part,i in jobs]
  for future in futures:future.result()
