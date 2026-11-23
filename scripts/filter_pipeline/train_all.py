from concurrent.futures import ProcessPoolExecutor
from common import PROTO
from jepa_stage import run

if __name__=='__main__':
 with ProcessPoolExecutor(max_workers=3) as pool:
  futures=[pool.submit(run,seed) for seed in PROTO['model_seeds']]
  for future in futures:future.result()
